"""Scoring logic and Rich report rendering for project health."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table
from rich.text import Text

from tff.core.config import FitnessFunctionsConfig, HealthPenaltiesConfig
from tff.core.report import CHECK_LABELS, CONNASCENCE_CATEGORIES, LintFinding

from tff.core.registry import normalize_check_name, registry

PROJECT_LEVEL_CHECKS: set[str] = registry.get_project_level_check_names()
CATEGORIES: dict[str, list[str]] = registry.get_categories()

CATEGORY_ALIASES: dict[str, str] = {
    "con": "Connascence of Name (CoN)",
    "connascence_of_name": "Connascence of Name (CoN)",
    "name": "Connascence of Name (CoN)",
    "cot": "Connascence of Type (CoT)",
    "connascence_of_type": "Connascence of Type (CoT)",
    "type": "Connascence of Type (CoT)",
    "cop": "Connascence of Position (CoP)",
    "connascence_of_position": "Connascence of Position (CoP)",
    "position": "Connascence of Position (CoP)",
    "com": "Connascence of Meaning (CoM)",
    "connascence_of_meaning": "Connascence of Meaning (CoM)",
    "meaning": "Connascence of Meaning (CoM)",
    "coa": "Connascence of Algorithm (CoA)",
    "connascence_of_algorithm": "Connascence of Algorithm (CoA)",
    "algorithm": "Connascence of Algorithm (CoA)",
    "cov": "Connascence of Value (CoV)",
    "connascence_of_value": "Connascence of Value (CoV)",
    "value": "Connascence of Value (CoV)",
    "dynamic_coupling": "Dynamic Coupling & DAG Structure",
    "coupling": "Dynamic Coupling & DAG Structure",
    "dag": "Dynamic Coupling & DAG Structure",
    "dynamic_coupling_dag_structure": "Dynamic Coupling & DAG Structure",
    "quality": "Quality & Metadata (Non-Connascence)",
    "metadata": "Quality & Metadata (Non-Connascence)",
    "quality_metadata": "Quality & Metadata (Non-Connascence)",
}


def normalize_category_name(name: str) -> str:
    """Normalize category name for lookup."""
    norm = normalize_check_name(name)
    alias_match = CATEGORY_ALIASES.get(name.lower().strip()) or CATEGORY_ALIASES.get(norm)
    if alias_match:
        return normalize_check_name(alias_match)
    return norm


def get_check_weight(
    check_name: str,
    config: FitnessFunctionsConfig,
) -> float:
    """Resolve weight for a given check name or category from config."""
    health_cfg = getattr(config, "health", None)
    if health_cfg is None:
        return 1.0

    weights = health_cfg.weights
    category_weights = health_cfg.category_weights
    check_def = registry.get(check_name)

    # 1. Direct check weight match
    candidate_names: list[str] = [check_name]
    if check_def is not None:
        candidate_names.append(check_def.id)
        if check_def.finding_check_id:
            candidate_names.append(check_def.finding_check_id)
        candidate_names.extend(check_def.aliases)

    candidate_norms = {normalize_check_name(c) for c in candidate_names}

    for k, w in weights.items():
        if normalize_check_name(k) in candidate_norms:
            return w

    # 2. Category weight match
    category: str | None = check_def.category if check_def is not None else None

    if category is not None:
        norm_cat = normalize_check_name(category)
        for k, w in category_weights.items():
            if normalize_category_name(k) == norm_cat:
                return w
        for k, w in weights.items():
            if normalize_category_name(k) == norm_cat:
                return w

    return 1.0


def is_check_enabled(
    config: FitnessFunctionsConfig, check_name: str, provider: str
) -> bool:
    """Determine if a check/rule is enabled in the configuration."""
    return registry.is_check_enabled(config, check_name, provider)


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
    scoped_models_count: int | None = None,
) -> dict[str, Any]:
    """Calculate health scores based on findings and enabled checks.

    When *scope* is given (a list of path prefixes such as
    ``["models/sources"]`` or ``["models/marts/marketing"]``), only findings
    whose ``path`` starts with one of those prefixes are considered. If
    *scoped_models_count* is provided, it is used as the denominator;
    otherwise, ``models_checked`` is re-derived from the paths that appear in the
    filtered findings (so the denominator reflects the scoped subset).
    Project-level checks (which have no path) are always excluded when a
    scope is active.
    """
    if scope:
        findings = [f for f in findings if _matches_scope(f.path, scope)]
        if scoped_models_count is not None:
            models_checked = scoped_models_count
        else:
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

    penalties = (
        config.health.penalties
        if hasattr(config, "health")
        else HealthPenaltiesConfig()
    )

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
            err_penalty = penalties.get_check_error_penalty(check, is_project_level=True)
            warn_penalty = penalties.get_check_warning_penalty(check, is_project_level=True)
            if any(f.severity == "error" for f in cf):
                check_scores[check] = max(0.0, 100.0 - err_penalty)
            elif any(f.severity == "warning" for f in cf):
                check_scores[check] = max(0.0, 100.0 - warn_penalty)
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
                err_mult = penalties.get_check_error_penalty(check, is_project_level=False)
                warn_mult = penalties.get_check_warning_penalty(check, is_project_level=False)
                score = 100.0 * (1.0 - (err_mult * E + warn_mult * W) / M)
                check_scores[check] = max(0.0, score)

    # Collect weights for enabled checks
    check_weights: dict[str, float] = {
        check: get_check_weight(check, config) for check in enabled_checks
    }

    # Calculate category scores
    category_scores: dict[str, float | None] = {}
    for cat_name, cat_checks in CATEGORIES.items():
        enabled_cat_checks = [c for c in cat_checks if c in enabled_checks]
        if not enabled_cat_checks:
            category_scores[cat_name] = None
        else:
            cat_total_weight = sum(check_weights[c] for c in enabled_cat_checks)
            if cat_total_weight > 0:
                category_scores[cat_name] = (
                    sum(check_scores[c] * check_weights[c] for c in enabled_cat_checks)
                    / cat_total_weight
                )
            else:
                category_scores[cat_name] = sum(check_scores[c] for c in enabled_cat_checks) / len(enabled_cat_checks)

    # Handle "Other Checks" category if findings exist for unknown checks
    unknown_enabled = [c for c in enabled_checks if c not in all_known_checks]
    if unknown_enabled:
        unknown_total_weight = sum(check_weights[c] for c in unknown_enabled)
        if unknown_total_weight > 0:
            category_scores["Other Checks"] = (
                sum(check_scores[c] * check_weights[c] for c in unknown_enabled)
                / unknown_total_weight
            )
        else:
            category_scores["Other Checks"] = sum(check_scores[c] for c in unknown_enabled) / len(unknown_enabled)
    else:
        category_scores["Other Checks"] = None

    # Calculate overall score
    if not enabled_checks:
        overall_score = 100.0
    else:
        overall_total_weight = sum(check_weights[c] for c in enabled_checks)
        if overall_total_weight > 0:
            overall_score = (
                sum(check_scores[c] * check_weights[c] for c in enabled_checks)
                / overall_total_weight
            )
        else:
            overall_score = sum(check_scores.values()) / len(enabled_checks)

    return {
        "overall_score": overall_score,
        "check_scores": check_scores,
        "category_scores": category_scores,
        "enabled_checks": enabled_checks,
        "check_findings": check_findings,
        "check_weights": check_weights,
        "models_checked": models_checked,
    }


DIMENSION_DISPLAY_NAMES: dict[str, str] = {
    "Dynamic Coupling & DAG Structure": "Architecture & DAG",
    "Quality & Metadata (Non-Connascence)": "Contract & Metadata",
    "Connascence of Algorithm (CoA)": "Connascence of Algorithm",
    "Connascence of Position (CoP)": "Connascence of Position",
    "Connascence of Value (CoV)": "Connascence of Value",
    "Connascence of Name (CoN)": "Connascence of Name",
    "Connascence of Type (CoT)": "Connascence of Type",
    "Connascence of Meaning (CoM)": "Connascence of Meaning",
}

SHORT_CHECK_LABELS: dict[str, str] = {
    "layer_integrity": "layer",
    "duplicate_ctes": "dup_cte",
    "banselectstar": "star",
    "ban_select_star": "star",
    "nomissingowner": "owner",
    "nomissingdescription": "desc",
    "nomissinggrain": "grain",
    "join_type_parity": "join_parity",
    "classificationmacros": "macro",
    "classification_macros": "macro",
    "sqlcomplexity": "complexity",
    "sql_complexity": "complexity",
    "nopositionalgroupbyororderby": "position",
    "no_positional_group_by_or_order_by": "position",
    "schema_contracts": "contract",
    "dependency_graph": "graph",
    "materialization_depth": "depth",
    "connascence_of_value": "value",
    "filenameequalsmodelname": "filename",
    "filename_equals_modelname": "filename",
}


def _get_action_phrase(check: str, count: int) -> str:
    """Format an actionable remediation command."""
    if check == "duplicate_ctes":
        return f"Refactor {count} duplicate CTE{'s' if count != 1 else ''}"
    if check == "layer_integrity":
        return f"Fix {count} layer integrity violation{'s' if count != 1 else ''}"
    if check in ("banselectstar", "ban_select_star"):
        return f"Replace {count} wildcard SELECT * {'query' if count == 1 else 'queries'}"
    if check in ("nomissingowner", "nomissingdescription", "nomissinggrain"):
        return f"Add missing contract metadata to {count} model{'s' if count != 1 else ''}"
    if check == "join_type_parity":
        return f"Align data types across {count} JOIN condition{'s' if count != 1 else ''}"
    return f"Resolve {count} {CHECK_LABELS.get(check, check)} defect{'s' if count != 1 else ''}"


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
    duration: float | None = None,
    fail_under: float | None = None,
    verbose: bool = False,
    project_root: Path | None = None,
) -> None:
    """Render project fitness score in architectural style."""
    console = console or Console()

    overall_score = scores["overall_score"]
    enabled_checks = scores["enabled_checks"]
    category_scores = scores["category_scores"]
    check_scores = scores["check_scores"]
    check_findings = scores["check_findings"]
    check_weights = scores.get("check_weights", {})

    score_color = "green" if overall_score >= 90 else "yellow" if overall_score >= 70 else "red"
    width = max(78, min(console.width - 2, 86)) if console.width else 78

    # 1. Header Block
    console.print("[bold]PROJECT FITNESS SCORE[/bold]")
    console.print("─" * width, style="dim")

    header_line = Text()
    header_line.append("OVERALL HEALTH", style="bold")
    pad_to_score = max(2, 47 - len("OVERALL HEALTH"))
    header_line.append(" " * pad_to_score)
    header_line.append(f"{overall_score:5.1f}%", style=f"bold {score_color}")

    if fail_under is not None and fail_under > 0:
        if overall_score < fail_under:
            header_line.append(f"  [FAIL: TARGET >= {fail_under:.1f}%]", style="bold red")
        else:
            header_line.append(f"  [PASS: TARGET >= {fail_under:.1f}%]", style="bold green")

    console.print(header_line)
    console.print("─" * width, style="dim")
    console.print()

    # 2. Dimension Table
    dim_table = Table(
        box=None,
        show_header=True,
        header_style="bold",
        padding=(0, 2, 0, 0),
    )
    dim_table.add_column("DIMENSION", style="bold", min_width=38)
    dim_table.add_column("SCORE", justify="right", width=7)
    dim_table.add_column("DEFECTS", justify="right", width=8)
    dim_table.add_column("DISTRIBUTION (0-100)", justify="left", width=20)

    for cat_name, cat_score in category_scores.items():
        if cat_score is None:
            continue
        cat_checks = CATEGORIES.get(cat_name, [c for c in enabled_checks if c not in CONNASCENCE_CATEGORIES])
        enabled_cat_checks = [c for c in cat_checks if c in enabled_checks]
        defects = sum(len(check_findings[c]) for c in enabled_cat_checks)

        c_color = "green" if cat_score >= 90 else "yellow" if cat_score >= 70 else "red"
        score_cell = Text(f"{cat_score:.1f}%", style=f"bold {c_color}")
        defects_cell = Text(
            str(defects),
            style="dim" if defects == 0 else ("bold red" if any(f.severity == "error" for c in enabled_cat_checks for f in check_findings[c]) else "bold yellow"),
        )
        bar_str = make_progress_bar(cat_score, width=10)
        bar_cell = Text.from_markup(f"[{c_color}]{bar_str}[/{c_color}]")
        display_name = DIMENSION_DISPLAY_NAMES.get(cat_name, cat_name)
        dim_table.add_row(display_name, score_cell, defects_cell, bar_cell)

    console.print(dim_table)
    console.print()

    # 3. Domain Breakdown
    console.print("[bold]DOMAIN BREAKDOWN[/bold]")
    console.print("─" * width, style="dim")

    domain_table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
    domain_table.add_column("Domain", style="bold", width=18)
    domain_table.add_column("Score", justify="right", width=7)
    domain_table.add_column("Issues", justify="right", width=11)
    domain_table.add_column("Breakdown", justify="left")

    domain_models: dict[str, set[str]] = defaultdict(set)
    roots_to_try = [project_root] if project_root else []
    roots_to_try.extend([Path.cwd(), Path.cwd().parent])

    for r in roots_to_try:
        if not r or not r.exists():
            continue
        for base in ("models", "definitions"):
            base_dir = r / base
            if base_dir.is_dir():
                for p in base_dir.rglob("*"):
                    if p.is_file() and p.suffix in (".sql", ".sqlx"):
                        rel = str(p.relative_to(r)).replace("\\", "/")
                        d_key = _domain_key(rel)
                        domain_models[d_key].add(rel)
        if domain_models:
            break

    for check in enabled_checks:
        for f in check_findings[check]:
            d_key = _domain_key(f.path)
            domain_models[d_key].add(f.path or (f.model or "project"))

    if not domain_models:
        domain_models["project"].add("project")

    penalties = (
        config.health.penalties
        if hasattr(config, "health")
        else HealthPenaltiesConfig()
    )

    domain_data: list[dict[str, Any]] = []
    for domain_label, model_set in domain_models.items():
        domain_findings = [
            f for check in enabled_checks for f in check_findings[check]
            if _domain_key(f.path) == domain_label
        ]
        total_issues = len(domain_findings)
        errors = sum(1 for f in domain_findings if f.severity == "error")
        warnings = sum(1 for f in domain_findings if f.severity == "warning")

        domain_models_checked = max(len(model_set), 1)

        if not domain_findings:
            domain_score = 100.0
        else:
            domain_by_check: dict[str, list[LintFinding]] = defaultdict(list)
            for f in domain_findings:
                domain_by_check[f.check].append(f)

            local_scores = []
            local_weights = []
            for check in enabled_checks:
                cf = domain_by_check.get(check, [])
                w = check_weights.get(check, 1.0)
                if not cf:
                    local_scores.append(100.0)
                    local_weights.append(w)
                else:
                    error_models = {f.model for f in cf if f.severity == "error" and f.model}
                    warning_models = {f.model for f in cf if f.severity == "warning" and f.model} - error_models
                    E = len(error_models) + sum(1 for f in cf if f.severity == "error" and not f.model)
                    W = len(warning_models) + sum(1 for f in cf if f.severity == "warning" and not f.model)
                    err_mult = penalties.get_check_error_penalty(check, is_project_level=False)
                    warn_mult = penalties.get_check_warning_penalty(check, is_project_level=False)
                    l_score = max(0.0, 100.0 * (1.0 - (err_mult * E + warn_mult * W) / domain_models_checked))
                    local_scores.append(l_score)
                    local_weights.append(w)

            tot_w = sum(local_weights)
            if tot_w > 0:
                domain_score = sum(s * w for s, w in zip(local_scores, local_weights)) / tot_w
            else:
                domain_score = sum(local_scores) / len(local_scores)

        check_counts: dict[str, int] = defaultdict(int)
        for f in domain_findings:
            short_lbl = SHORT_CHECK_LABELS.get(f.check, f.check.split("_")[0])
            check_counts[short_lbl] += 1

        sorted_counts = sorted(check_counts.items(), key=lambda x: x[1], reverse=True)
        breakdown_parts = [f"{cnt} {lbl}" for lbl, cnt in sorted_counts[:4]]
        breakdown_str = f"({', '.join(breakdown_parts)})" if breakdown_parts else ""

        # Clean display label
        clean_label = domain_label
        for prefix in ("models/", "definitions/"):
            if clean_label.startswith(prefix):
                clean_label = clean_label[len(prefix):]

        domain_data.append({
            "label": clean_label,
            "raw_label": domain_label,
            "score": domain_score,
            "issues": total_issues,
            "errors": errors,
            "warnings": warnings,
            "breakdown": breakdown_str,
        })

    domain_data.sort(key=lambda d: (d["score"], -d["issues"]))

    for d in domain_data:
        d_color = "green" if d["score"] >= 90 else "yellow" if d["score"] >= 70 else "red"
        d_score_cell = Text(f"{d['score']:.1f}%", style=f"bold {d_color}")
        issues_text = f"{d['issues']} issue{'s' if d['issues'] != 1 else ''}"
        issues_cell = Text(issues_text, style="dim" if d["issues"] == 0 else ("bold red" if d["errors"] else "bold yellow"))
        breakdown_cell = Text(d["breakdown"], style="dim")
        domain_table.add_row(d["label"], d_score_cell, issues_cell, breakdown_cell)

    console.print(domain_table)
    console.print("─" * width, style="dim")

    # 4. STATUS & ACTION
    models_count = scores.get("models_checked") or sum(len(m) for m in domain_models.values())
    status_line = f"STATUS: {len(enabled_checks)} checks evaluated across {models_count} models."
    console.print(status_line)

    overall_total_weight = sum(check_weights.get(c, 1.0) for c in enabled_checks)
    penalties_list: list[tuple[float, str, str]] = []
    if overall_total_weight > 0:
        for check in enabled_checks:
            score = check_scores.get(check, 100.0)
            if score < 100.0:
                weight = check_weights.get(check, 1.0)
                pts_lost = ((100.0 - score) * weight) / overall_total_weight
                label = CHECK_LABELS.get(check, check)
                penalties_list.append((pts_lost, label, check))

    penalties_list.sort(key=lambda x: x[0], reverse=True)

    if penalties_list:
        pts_lost, top_label, top_check = penalties_list[0]
        cnt = len(check_findings[top_check])
        action_verb = _get_action_phrase(top_check, cnt)
        target = fail_under if (fail_under is not None and fail_under > 0) else 80.0
        if overall_score < target:
            console.print(f"ACTION: {action_verb} to raise score above {target:.1f}%.")
        else:
            console.print(f"ACTION: {action_verb} to improve project fitness.")
    else:
        console.print("ACTION: All fitness functions satisfied. Fitness score is optimal.")

    if group_by == "domain":
        console.print()
        _render_health_by_domain(scores, console, config=config, verbose=verbose)
    elif verbose:
        console.print()
        _render_health_by_connascence(
            scores, enabled_checks, check_scores, check_findings, console, verbose=verbose
        )
    else:
        console.print("\n[dim]Run [bold]tff explain <rule>[/bold] for remediation guides. Use [bold]--verbose[/bold] to expand all passing and disabled checks.[/dim]")


def _format_health_check_desc(
    icon_markup: str,
    check: str,
    label: str,
    weight_str: str = "",
    disabled: bool = False,
) -> Text:
    """Format check description column with status icon, label, and OSC-8 hyperlink if available."""
    docs_url = registry.get_docs_url(check)
    desc = Text()
    if disabled:
        desc.append("  - ", style="dim")
        desc.append(label, style=f"dim link {docs_url}" if docs_url else "dim")
        desc.append(" ")
        desc.append(f"({check})", style=f"dim link {docs_url}" if docs_url else "dim")
        return desc

    desc.append("  ")
    desc.append_text(Text.from_markup(icon_markup))
    desc.append(" ")
    desc.append(label, style=f"link {docs_url}" if docs_url else None)
    desc.append(" ")
    check_inner = f"({check}{weight_str})"
    desc.append(check_inner, style=f"dim link {docs_url}" if docs_url else "dim")
    return desc


def _render_health_by_connascence(
    scores: dict[str, Any],
    enabled_checks: set[str],
    check_scores: dict[str, float],
    check_findings: Any,
    console: Console,
    verbose: bool = False,
) -> None:
    """Render detailed breakdown grouped by connascence category."""
    console.print("[bold]Detailed Breakdown by Check[/bold]")

    check_weights = scores.get("check_weights", {})
    first_cat = True
    collapsed_count = 0
    for cat_name, cat_checks in CATEGORIES.items():
        # Only print category if it contains enabled checks
        enabled_cat_checks = [c for c in cat_checks if c in enabled_checks]
        if not enabled_cat_checks:
            continue

        if not first_cat:
            console.print()
        first_cat = False

        console.print(f"[bold]● {cat_name}[/bold]")

        table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
        table.add_column(min_width=38)
        table.add_column(width=22, no_wrap=True)
        table.add_column(no_wrap=True)

        if verbose:
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

                    weight = check_weights.get(check, 1.0)
                    weight_str = f" · weight: {weight:g}" if weight != 1.0 else ""
                    check_desc = _format_health_check_desc(icon, check, label, weight_str=weight_str)
                    bar = make_progress_bar(score, width=10)
                    score_cell = Text.from_markup(f"{bar} {score_text}")

                    table.add_row(check_desc, score_cell, Text.from_markup(violation_text))
                else:
                    check_desc = _format_health_check_desc("-", check, label, disabled=True)
                    table.add_row(check_desc, Text("Disabled", style="dim"), "")
        else:
            failing = [c for c in enabled_cat_checks if check_scores.get(c, 100.0) < 100.0]
            passing = [c for c in enabled_cat_checks if check_scores.get(c, 100.0) >= 100.0]
            disabled = [c for c in cat_checks if c not in enabled_checks]

            # 1. Failing / warning checks
            for check in failing:
                label = CHECK_LABELS.get(check, check)
                score = check_scores[check]
                cf = check_findings[check]

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

                weight = check_weights.get(check, 1.0)
                weight_str = f" · weight: {weight:g}" if weight != 1.0 else ""
                check_desc = _format_health_check_desc(icon, check, label, weight_str=weight_str)
                bar = make_progress_bar(score, width=10)
                score_cell = Text.from_markup(f"{bar} {score_text}")

                table.add_row(check_desc, score_cell, Text.from_markup(violation_text))

            # 2. Passing checks
            if passing:
                if len(passing) == 1 and not failing:
                    c = passing[0]
                    label = CHECK_LABELS.get(c, c)
                    weight = check_weights.get(c, 1.0)
                    weight_str = f" · weight: {weight:g}" if weight != 1.0 else ""
                    check_desc = _format_health_check_desc("[green]✔[/green]", c, label, weight_str=weight_str)
                    bar = make_progress_bar(100.0, width=10)
                    score_cell = Text.from_markup(f"{bar} [green]100.0%[/green]")
                    table.add_row(check_desc, score_cell, "")
                else:
                    collapsed_count += len(passing)
                    if not failing:
                        desc_text = f"  [green]✔[/green] All {len(passing)} checks scored [green]100.0%[/green]"
                    else:
                        desc_text = f"  [green]✔[/green] {len(passing)} check{'s' if len(passing) != 1 else ''} passing"
                    bar = make_progress_bar(100.0, width=10)
                    score_cell = Text.from_markup(f"{bar} [green]100.0%[/green]")
                    table.add_row(Text.from_markup(desc_text), score_cell, "")

            # 3. Disabled checks
            if disabled:
                collapsed_count += len(disabled)
                desc = Text("  - ", style="dim")
                desc.append(
                    f"{len(disabled)} check{'s' if len(disabled) != 1 else ''} disabled (",
                    style="dim",
                )
                for i, c in enumerate(disabled):
                    if i > 0:
                        desc.append(", ", style="dim")
                    url = registry.get_docs_url(c)
                    desc.append(c, style=f"dim link {url}" if url else "dim")
                desc.append(")", style="dim")
                table.add_row(desc, Text("Disabled", style="dim"), "")

        console.print(table)

    # Print other checks if any
    all_known_checks: set[str] = set()
    for cat_checks in CATEGORIES.values():
        all_known_checks.update(cat_checks)
    unknown_enabled = [c for c in enabled_checks if c not in all_known_checks]
    if unknown_enabled:
        if not first_cat:
            console.print()
        console.print("[bold]● Other Checks[/bold]")

        table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
        table.add_column(min_width=38)
        table.add_column(width=22, no_wrap=True)
        table.add_column(no_wrap=True)

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

            weight = check_weights.get(check, 1.0)
            weight_str = f" · weight: {weight:g}" if weight != 1.0 else ""
            check_desc = _format_health_check_desc(icon, check, label, weight_str=weight_str)
            bar = make_progress_bar(score, width=10)
            score_cell = Text.from_markup(f"{bar} {score_text}")

            table.add_row(check_desc, score_cell, Text.from_markup(violation_text))

        console.print(table)

    if not verbose and collapsed_count > 0:
        console.print()
        console.print("[dim]Use [bold]--verbose[/bold] to expand all passing and disabled checks.[/dim]")

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
    base_folder = None
    models_index = None
    for base in ("models", "definitions"):
        if base in parts:
            base_folder = base
            models_index = parts.index(base)
            break
    if models_index is None:
        return path
    if len(parts) <= models_index + 1:
        return path
    layer = parts[models_index + 1]
    # Check whether the third component is a subdirectory (domain) or a model file
    if len(parts) > models_index + 2:
        third = parts[models_index + 2]
        if not third.endswith((".sql", ".sqlx")):
            return f"{base_folder}/{layer}/{third}"
    return f"{base_folder}/{layer}"



def _render_health_by_domain(
    scores: dict[str, Any],
    console: Console,
    config: FitnessFunctionsConfig | None = None,
    verbose: bool = False,
) -> None:
    """Render detailed breakdown grouped by domain (path segment after models/)."""
    penalties = (
        config.health.penalties
        if config and hasattr(config, "health")
        else HealthPenaltiesConfig()
    )
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
        console.print("[bold]Detailed Breakdown by Domain[/bold]")
        console.print("[dim]No findings in selected scope.[/dim]")
        console.print()
        return

    # Determine which checks appear in each domain
    console.print("[bold]Detailed Breakdown by Domain[/bold]")
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
        header_line.append(f"● {domain_label}", style="bold")
        header_line.append("  ")
        header_line.append(error_part)
        header_line.append("  ·  ", style="dim")
        header_line.append(warn_part)
        console.print(header_line)

        table = Table(box=None, show_header=False, padding=(0, 2, 0, 0))
        table.add_column(min_width=38)
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
                err_mult = penalties.get_check_error_penalty(check, is_project_level=False)
                warn_mult = penalties.get_check_warning_penalty(check, is_project_level=False)
                local_score = max(0.0, 100.0 * (1.0 - (err_mult * E + warn_mult * W) / domain_models_checked))
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

            check_desc = _format_health_check_desc(icon, check, label)
            bar = make_progress_bar(local_score, width=10)
            score_cell = Text.from_markup(f"{bar} {score_text}")
            table.add_row(check_desc, score_cell, Text.from_markup(violation_text))

        console.print(table)

    console.print()
