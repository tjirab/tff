"""Scoring logic and Rich report rendering for project health."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from tff.core.config import FitnessFunctionsConfig
from tff.core.report import CHECK_LABELS, CONNASCENCE_CATEGORIES, LintFinding

PROJECT_LEVEL_CHECKS = {
    "layer_integrity",
    "custom_exclusions",
    "schema_contracts",
    "dependency_graph",
    "materialization_depth",
}

CATEGORIES = {
    "Connascence of Name (CoN)": [
        "banselectstar",
        "filenameequalsmodelname",
        "columnnames",
        "martmodelnamingconvention",
        "ambiguousorinvalidcolumn",
        "invalidselectstarexpansion",
    ],
    "Connascence of Type (CoT)": [
        "columntypes",
        "schema_contracts",
    ],
    "Connascence of Position (CoP)": [
        "nopositionalgroupbyororderby",
    ],
    "Connascence of Meaning (CoM)": [
        "classificationmacros",
    ],
    "Dynamic Coupling & DAG Structure": [
        "layer_integrity",
        "custom_exclusions",
        "dependency_graph",
        "materialization_depth",
        "environmentagnosticreferences",
    ],
    "Quality & Metadata (Non-Connascence)": [
        "nomissingowner",
        "nomissingdescription",
        "nomissinggrain",
        "nomissingnotnull",
        "nomissinguniquevalues",
        "sqlcomplexity",
    ],
}


def is_check_enabled(config: FitnessFunctionsConfig, check_name: str, provider: str) -> bool:
    """Determine if a check/rule is enabled in the configuration."""
    if check_name == "layer_integrity":
        return config.checks.layer_integrity.enabled
    if check_name == "custom_exclusions":
        return config.checks.custom_exclusions.enabled
    if check_name == "schema_contracts":
        return config.checks.schema_contracts.enabled
    if check_name == "dependency_graph":
        return config.checks.dependency_graph.enabled
    if check_name == "materialization_depth":
        return config.checks.materialization_depth.enabled
    if check_name == "classificationmacros":
        return config.rules.classification_macros.enabled
    if check_name == "sqlcomplexity":
        return config.rules.sql_complexity.enabled
    if check_name == "martmodelnamingconvention":
        return config.rules.mart_naming.enabled
    if check_name == "columnnames":
        return config.rules.column_names.enabled
    if check_name == "columntypes":
        return config.rules.column_types.enabled
    if check_name == "filenameequalsmodelname":
        return config.rules.filename_equals_modelname.enabled
    if check_name == "banselectstar":
        return config.rules.ban_select_star.enabled
    if check_name == "nopositionalgroupbyororderby":
        return config.rules.no_positional_group_by_or_order_by.enabled
    if check_name == "environmentagnosticreferences":
        return config.rules.environment_agnostic_references.enabled

    # Metadata sub-rules
    if check_name == "nomissingowner":
        return config.rules.metadata.enabled and config.rules.metadata.owner
    if check_name == "nomissingdescription":
        return config.rules.metadata.enabled and config.rules.metadata.description
    if check_name == "nomissinggrain":
        return config.rules.metadata.enabled and config.rules.metadata.grain
    if check_name == "nomissingnotnull":
        return config.rules.metadata.enabled and config.rules.metadata.not_null
    if check_name == "nomissinguniquevalues":
        return config.rules.metadata.enabled and config.rules.metadata.unique_values

    # SQLMesh native rules
    if check_name in {"ambiguousorinvalidcolumn", "invalidselectstarexpansion"}:
        return provider == "sqlmesh"

    return False


def _matches_scope(finding_path: str | None, scope: list[str]) -> bool:
    """Return True if *finding_path* starts with any of the scope prefixes."""
    if finding_path is None:
        return False
    # Normalise separators so both 'models/sources' and 'models\\sources' work
    norm_path = finding_path.replace("\\", "/")
    return any(
        norm_path == prefix.rstrip("/") or norm_path.startswith(prefix.rstrip("/") + "/")
        for prefix in scope
    )


def calculate_health_scores(
    findings: list[LintFinding],
    models_checked: int,
    config: FitnessFunctionsConfig,
    provider: str,
    *,
    scope: list[str] | None = None,
) -> dict[str, Any]:
    """Calculate health scores based on findings and enabled checks.

    When *scope* is given (a list of path prefixes such as
    ``["models/sources"]`` or ``["models/marts/marketing"]``), only findings
    whose ``path`` starts with one of those prefixes are considered and
    ``models_checked`` is re-derived from the paths that appear in the
    filtered findings (so the denominator reflects the scoped subset).
    Project-level checks (which have no path) are always excluded when a
    scope is active.
    """
    if scope:
        findings = [f for f in findings if _matches_scope(f.path, scope)]
        # Re-derive models_checked from the scoped findings' unique model paths
        scoped_model_paths: set[str] = set()
        for f in findings:
            if f.path:
                scoped_model_paths.add(f.path)
        models_checked = len(scoped_model_paths)
    enabled_checks = set()
    all_known_checks = set()
    for cat_checks in CATEGORIES.values():
        all_known_checks.update(cat_checks)

    # Gather enabled status
    for check in all_known_checks:
        if is_check_enabled(config, check, provider):
            enabled_checks.add(check)

    # If any finding check is not in all_known_checks, we treat it as enabled
    for f in findings:
        if f.check not in all_known_checks:
            enabled_checks.add(f.check)

    check_scores: dict[str, float] = {}
    check_findings: dict[str, list[LintFinding]] = defaultdict(list)
    for f in findings:
        check_findings[f.check].append(f)

    # Calculate scores per check
    for check in enabled_checks:
        cf = check_findings[check]
        if not cf:
            check_scores[check] = 100.0
            continue

        if check in PROJECT_LEVEL_CHECKS:
            # Project level check
            if any(f.severity == "error" for f in cf):
                check_scores[check] = 0.0
            elif any(f.severity == "warning" for f in cf):
                check_scores[check] = 50.0
            else:
                check_scores[check] = 100.0
        else:
            # Model level check
            error_count = 0
            warning_count = 0
            error_models = set()
            warning_models = set()
            for f in cf:
                if f.severity == "error":
                    if f.model:
                        error_models.add(f.model)
                    else:
                        error_count += 1
                else:
                    if f.model:
                        warning_models.add(f.model)
                    else:
                        warning_count += 1

            # Warnings count only for models without errors
            warning_models = warning_models - error_models
            E = len(error_models) + error_count
            W = len(warning_models) + warning_count
            M = models_checked

            if M <= 0:
                check_scores[check] = 100.0
            else:
                score = 100.0 * (1.0 - (E + 0.5 * W) / M)
                check_scores[check] = max(0.0, score)

    # Calculate category scores
    category_scores: dict[str, float | None] = {}
    for cat_name, cat_checks in CATEGORIES.items():
        enabled_cat_checks = [c for c in cat_checks if c in enabled_checks]
        if not enabled_cat_checks:
            category_scores[cat_name] = None
        else:
            category_scores[cat_name] = sum(check_scores[c] for c in enabled_cat_checks) / len(enabled_cat_checks)

    # Handle "Other Checks" category if findings exist for unknown checks
    unknown_enabled = [c for c in enabled_checks if c not in all_known_checks]
    if unknown_enabled:
        category_scores["Other Checks"] = sum(check_scores[c] for c in unknown_enabled) / len(unknown_enabled)
    else:
        category_scores["Other Checks"] = None

    # Calculate overall score
    if not enabled_checks:
        overall_score = 100.0
    else:
        overall_score = sum(check_scores.values()) / len(enabled_checks)

    return {
        "overall_score": overall_score,
        "check_scores": check_scores,
        "category_scores": category_scores,
        "enabled_checks": enabled_checks,
        "check_findings": check_findings,
    }


def make_progress_bar(score: float, width: int = 15) -> str:
    """Generate a colored progress bar block string."""
    filled = int(round(score / 100 * width))
    bar = "█" * filled + "░" * (width - filled)
    
    if score >= 90:
        return f"[green]{bar}[/green]"
    if score >= 70:
        return f"[yellow]{bar}[/yellow]"
    return f"[red]{bar}[/red]"


def render_health_report(
    scores: dict[str, Any],
    config: FitnessFunctionsConfig,
    provider: str,
    console: Console | None = None,
    *,
    group_by: str = "connascence",
) -> None:
    """Render a beautiful CLI health report using rich.

    Parameters
    ----------
    group_by:
        ``"connascence"`` (default) groups the detailed breakdown by
        connascence category.  ``"domain"`` groups by the path segment
        directly under ``models/`` and optionally a sub-domain, e.g.
        ``models/sources``, ``models/marts/marketing``.
    """
    console = console or Console()
    
    overall_score = scores["overall_score"]
    enabled_checks = scores["enabled_checks"]
    category_scores = scores["category_scores"]
    check_scores = scores["check_scores"]
    check_findings = scores["check_findings"]
    
    score_color = "green" if overall_score >= 90 else "yellow" if overall_score >= 70 else "red"
    
    score_panel = Panel(
        Text.assemble(
            ("Overall Project Health Score: ", "bold white"),
            (f"{overall_score:.1f}%", f"bold {score_color}"),
            ("\n", ""),
            (f"Active checks: {len(enabled_checks)}  ·  Categories: {sum(1 for v in category_scores.values() if v is not None)}", "dim")
        ),
        title=f"[bold {score_color}]TFF PROJECT HEALTH REPORT[/bold {score_color}]",
        border_style=score_color,
        padding=(1, 2),
    )
    console.print(score_panel)
    console.print()
    
    # 1. Summary Table
    console.print("[bold cyan]Health Score by Category[/bold cyan]")
    summary_table = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold cyan",
        padding=(0, 2, 0, 0),
    )
    summary_table.add_column("Category", style="bold", no_wrap=True)
    summary_table.add_column("Checks", justify="center", no_wrap=True)
    summary_table.add_column("Errors", justify="right", no_wrap=True)
    summary_table.add_column("Warnings", justify="right", no_wrap=True)
    summary_table.add_column("Score", justify="right", no_wrap=True)
    
    for cat_name, cat_score in category_scores.items():
        if cat_score is None:
            continue
            
        cat_checks = CATEGORIES.get(cat_name, [c for c in enabled_checks if c not in CONNASCENCE_CATEGORIES])
        enabled_cat_checks = [c for c in cat_checks if c in enabled_checks]
        
        # Count errors & warnings
        errors = 0
        warnings = 0
        for c in enabled_cat_checks:
            for f in check_findings[c]:
                if f.severity == "error":
                    errors += 1
                else:
                    warnings += 1
                    
        total_in_cat = len(cat_checks) if cat_name in CATEGORIES else len(enabled_cat_checks)
        checks_ratio = f"{len(enabled_cat_checks)}/{total_in_cat}"
        
        error_cell = Text(str(errors) if errors else "·", style="bold red" if errors else "dim")
        warn_cell = Text(str(warnings) if warnings else "·", style="bold yellow" if warnings else "dim")
        
        score_color = "green" if cat_score >= 90 else "yellow" if cat_score >= 70 else "red"
        score_cell = Text(f"{cat_score:.1f}%", style=f"bold {score_color}")
        
        summary_table.add_row(
            cat_name,
            checks_ratio,
            error_cell,
            warn_cell,
            score_cell,
        )
        
    console.print(summary_table)
    console.print()
    
    # 2. Detailed Breakdown
    if group_by == "domain":
        _render_health_by_domain(scores, console)
    else:
        _render_health_by_connascence(scores, enabled_checks, check_scores, check_findings, console)


def _render_health_by_connascence(
    scores: dict[str, Any],
    enabled_checks: set[str],
    check_scores: dict[str, float],
    check_findings: Any,
    console: Console,
) -> None:
    """Render detailed breakdown grouped by connascence category."""
    console.print("[bold cyan]Detailed Breakdown by Check[/bold cyan]")

    table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
    table.add_column()
    table.add_column(width=22, no_wrap=True)
    table.add_column(no_wrap=True)

    first_cat = True
    for cat_name, cat_checks in CATEGORIES.items():
        # Only print category if it contains enabled checks
        enabled_cat_checks = [c for c in cat_checks if c in enabled_checks]
        if not enabled_cat_checks:
            continue

        if not first_cat:
            table.add_row("", "", "")
        first_cat = False

        table.add_row(Text.from_markup(f"[bold cyan]● {cat_name}[/bold cyan]"), "", "")

        for check in cat_checks:
            label = CHECK_LABELS.get(check, check)

            if check in enabled_checks:
                score = check_scores[check]
                cf = check_findings[check]

                # Determine status icon and color
                if score == 100.0:
                    icon = "[green]✔[/green]"
                    score_text = "[green]100.0%[/green]"
                    violation_text = ""
                else:
                    icon_char = "✘" if score < 70 else "⚠"
                    color = "red" if score < 70 else "yellow"
                    icon = f"[{color}]{icon_char}[/{color}]"
                    score_text = f"[{color}]{score:.1f}%[/{color}]"

                    errors = sum(1 for f in cf if f.severity == "error")
                    warnings = sum(1 for f in cf if f.severity == "warning")
                    parts = []
                    if errors:
                        parts.append(f"{errors} error{'s' if errors != 1 else ''}")
                    if warnings:
                        parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
                    violation_text = f"[dim]({', '.join(parts)})[/dim]"

                check_desc = Text.from_markup(f"  {icon} {label}\n    [dim]({check})[/dim]")
                bar = make_progress_bar(score, width=10)
                score_cell = Text.from_markup(f"{bar} {score_text}")

                table.add_row(check_desc, score_cell, Text.from_markup(violation_text))
            else:
                check_desc = Text.from_markup(f"  [dim]- {label}\n    ({check})[/dim]")
                table.add_row(check_desc, Text("Disabled", style="dim"), "")

    # Print other checks if any
    all_known_checks: set[str] = set()
    for cat_checks in CATEGORIES.values():
        all_known_checks.update(cat_checks)
    unknown_enabled = [c for c in enabled_checks if c not in all_known_checks]
    if unknown_enabled:
        if not first_cat:
            table.add_row("", "", "")
        table.add_row(Text.from_markup("[bold cyan]● Other Checks[/bold cyan]"), "", "")

        for check in unknown_enabled:
            label = CHECK_LABELS.get(check, check)
            score = check_scores[check]
            cf = check_findings[check]

            if score == 100.0:
                icon = "[green]✔[/green]"
                score_text = "[green]100.0%[/green]"
                violation_text = ""
            else:
                icon_char = "✘" if score < 70 else "⚠"
                color = "red" if score < 70 else "yellow"
                icon = f"[{color}]{icon_char}[/{color}]"
                score_text = f"[{color}]{score:.1f}%[/{color}]"

                errors = sum(1 for f in cf if f.severity == "error")
                warnings = sum(1 for f in cf if f.severity == "warning")
                parts = []
                if errors:
                    parts.append(f"{errors} error{'s' if errors != 1 else ''}")
                if warnings:
                    parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
                violation_text = f"[dim]({', '.join(parts)})[/dim]"

            check_desc = Text.from_markup(f"  {icon} {label}\n    [dim]({check})[/dim]")
            bar = make_progress_bar(score, width=10)
            score_cell = Text.from_markup(f"{bar} {score_text}")

            table.add_row(check_desc, score_cell, Text.from_markup(violation_text))

    console.print(table)
    console.print()


def _domain_key(path: str | None) -> str:
    """Return a display key like 'models/sources' or 'models/marts/marketing'.

    A model sitting directly in the layer folder (``models/sources/model.sql``)
    is reported as ``models/sources``.  A model in a subdirectory
    (``models/marts/marketing/model.sql``) is reported as
    ``models/marts/marketing``.
    """
    if path is None:
        return "Project-level"
    parts = Path(path).parts
    try:
        models_index = parts.index("models")
    except ValueError:
        return path
    if len(parts) <= models_index + 1:
        return path
    layer = parts[models_index + 1]
    # Check whether the third component is a subdirectory (domain) or a .sql file
    if len(parts) > models_index + 2:
        third = parts[models_index + 2]
        if not third.endswith(".sql"):
            return f"models/{layer}/{third}"
    return f"models/{layer}"



def _render_health_by_domain(
    scores: dict[str, Any],
    console: Console,
) -> None:
    """Render detailed breakdown grouped by domain (path segment after models/)."""
    check_findings = scores["check_findings"]
    enabled_checks = scores["enabled_checks"]
    check_scores = scores["check_scores"]

    # Collect all findings from enabled checks
    all_findings: list[LintFinding] = []
    for check in enabled_checks:
        all_findings.extend(check_findings[check])

    # Bucket by domain key
    by_domain: dict[str, list[LintFinding]] = defaultdict(list)
    for f in all_findings:
        by_domain[_domain_key(f.path)].append(f)

    if not by_domain:
        console.print("[bold cyan]Detailed Breakdown by Domain[/bold cyan]")
        console.print("[dim]No findings in selected scope.[/dim]")
        console.print()
        return

    # Determine which checks appear in each domain
    console.print("[bold cyan]Detailed Breakdown by Domain[/bold cyan]")
    first_domain = True
    for domain_label in sorted(by_domain):
        domain_findings = by_domain[domain_label]

        errors_total = sum(1 for f in domain_findings if f.severity == "error")
        warnings_total = sum(1 for f in domain_findings if f.severity == "warning")

        # Per-check scores within this domain
        domain_by_check: dict[str, list[LintFinding]] = defaultdict(list)
        for f in domain_findings:
            domain_by_check[f.check].append(f)

        # Unique model paths seen in this domain (for denominator)
        domain_model_paths = {f.path for f in domain_findings if f.path}
        domain_models_checked = len(domain_model_paths)

        # Summary colour for the domain header
        err_style = "bold red" if errors_total else "dim"
        warn_style = "bold yellow" if warnings_total else "dim"
        error_part = Text(f"{errors_total} error{'s' if errors_total != 1 else ''}", style=err_style)
        warn_part = Text(f"{warnings_total} warning{'s' if warnings_total != 1 else ''}", style=warn_style)

        if not first_domain:
            console.print()
        first_domain = False

        header_line = Text()
        header_line.append(f"● {domain_label}", style="bold cyan")
        header_line.append("  ")
        header_line.append(error_part)
        header_line.append("  ·  ", style="dim")
        header_line.append(warn_part)
        console.print(header_line)

        table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
        table.add_column()
        table.add_column(width=22, no_wrap=True)
        table.add_column(no_wrap=True)

        for check in sorted(domain_by_check):
            label = CHECK_LABELS.get(check, check)
            cf = domain_by_check[check]
            errors = sum(1 for f in cf if f.severity == "error")
            warnings = sum(1 for f in cf if f.severity == "warning")

            # Compute a local score for this domain/check combination
            if domain_models_checked > 0:
                error_models = {f.model for f in cf if f.severity == "error" and f.model}
                warning_models = {f.model for f in cf if f.severity == "warning" and f.model} - error_models
                E = len(error_models) + sum(1 for f in cf if f.severity == "error" and not f.model)
                W = len(warning_models) + sum(1 for f in cf if f.severity == "warning" and not f.model)
                local_score = max(0.0, 100.0 * (1.0 - (E + 0.5 * W) / domain_models_checked))
            else:
                local_score = check_scores.get(check, 100.0)

            if local_score == 100.0:
                icon = "[green]✔[/green]"
                score_text = "[green]100.0%[/green]"
                violation_text = ""
            else:
                icon_char = "✘" if local_score < 70 else "⚠"
                color = "red" if local_score < 70 else "yellow"
                icon = f"[{color}]{icon_char}[/{color}]"
                score_text = f"[{color}]{local_score:.1f}%[/{color}]"
                parts = []
                if errors:
                    parts.append(f"{errors} error{'s' if errors != 1 else ''}")
                if warnings:
                    parts.append(f"{warnings} warning{'s' if warnings != 1 else ''}")
                violation_text = f"[dim]({', '.join(parts)})[/dim]"

            check_desc = Text.from_markup(f"  {icon} {label}\n    [dim]({check})[/dim]")
            bar = make_progress_bar(local_score, width=10)
            score_cell = Text.from_markup(f"{bar} {score_text}")
            table.add_row(check_desc, score_cell, Text.from_markup(violation_text))

        console.print(table)

    console.print()
