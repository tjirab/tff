"""Shared lint finding types and report rendering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

Severity = Literal["error", "warning"]

CHECK_LABELS: dict[str, str] = {
    "classificationmacros": "Classification macros",
    "sqlcomplexity": "SQL complexity",
    "layer_integrity": "Layer integrity",
    "custom_exclusions": "Custom exclusions",
    "schema_contracts": "Schema contracts",
    "dependency_graph": "Dependency graph",
    "nomissinggrain": "Missing grain",
    "nomissingowner": "Missing owner",
    "nomissingdescription": "Missing description",
    "nomissingaudits": "Missing audits",
    "nomissingnotnull": "Missing not_null audit",
    "nomissinguniquevalues": "Missing unique_values audit",
    "banselectstar": "No SELECT *",
    "filenameequalsmodelname": "Filename equals model name",
    "columntypes": "Column types",
    "columnnames": "Column names",
    "martmodelnamingconvention": "Mart naming convention",
    "ambiguousorinvalidcolumn": "Ambiguous/invalid column",
    "invalidselectstarexpansion": "Invalid SELECT * expansion",
    "nopositionalgroupbyororderby": "No positional GROUP BY or ORDER BY",
    "materialization_depth": "Materialization depth",
    "environmentagnosticreferences": "Environment-agnostic references",
}

CONNASCENCE_CATEGORIES: dict[str, str] = {
    # Connascence of Name (CoN)
    "banselectstar": "Connascence of Name (CoN)",
    "filenameequalsmodelname": "Connascence of Name (CoN)",
    "columnnames": "Connascence of Name (CoN)",
    "martmodelnamingconvention": "Connascence of Name (CoN)",
    "ambiguousorinvalidcolumn": "Connascence of Name (CoN)",
    "invalidselectstarexpansion": "Connascence of Name (CoN)",

    # Connascence of Type (CoT)
    "columntypes": "Connascence of Type (CoT)",
    "schema_contracts": "Connascence of Type (CoT)",

    # Connascence of Position (CoP)
    "nopositionalgroupbyororderby": "Connascence of Position (CoP)",

    # Connascence of Meaning (CoM)
    "classificationmacros": "Connascence of Meaning (CoM)",

    # Dynamic Coupling
    "layer_integrity": "Dynamic Coupling & DAG Structure",
    "custom_exclusions": "Dynamic Coupling & DAG Structure",
    "dependency_graph": "Dynamic Coupling & DAG Structure",
    "materialization_depth": "Dynamic Coupling & DAG Structure",
    "environmentagnosticreferences": "Dynamic Coupling & DAG Structure",


    # Quality & Metadata
    "nomissingowner": "Quality & Metadata (Non-Connascence)",
    "nomissingdescription": "Quality & Metadata (Non-Connascence)",
    "nomissinggrain": "Quality & Metadata (Non-Connascence)",
    "nomissingaudits": "Quality & Metadata (Non-Connascence)",
    "nomissingnotnull": "Quality & Metadata (Non-Connascence)",
    "nomissinguniquevalues": "Quality & Metadata (Non-Connascence)",
    "sqlcomplexity": "Quality & Metadata (Non-Connascence)",
}

ARCHITECTURAL_CHECKS = frozenset(
    {
        "layer_integrity",
        "custom_exclusions",
        "schema_contracts",
        "dependency_graph",
    }
)

ALWAYS_VISIBLE_CHECKS = [
    *ARCHITECTURAL_CHECKS,
    "sqlcomplexity",
    "classificationmacros",
]


@dataclass(frozen=True)
class LintFinding:
    check: str
    severity: Severity
    message: str
    model: str | None = None
    path: str | None = None


def normalize_model_name(name: str) -> str:
    parts = name.replace('"', "").split(".")
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    return name


def format_message(message: str | list[str]) -> str:
    if isinstance(message, list):
        return "; ".join(str(item) for item in message)
    return str(message)


def _summary_check_names(
    executed_checks: list[str] | None,
    by_check: dict[str, dict[Severity, int]],
) -> list[str]:
    if executed_checks is None:
        return sorted(set(ALWAYS_VISIBLE_CHECKS) | set(by_check))

    names: list[str] = []
    for check in executed_checks:
        if check == "sqlmesh":
            from_findings = {
                name for name in by_check if name not in ARCHITECTURAL_CHECKS
            }
            if from_findings:
                names.extend(from_findings)
            else:
                names.extend(
                    name
                    for name in ALWAYS_VISIBLE_CHECKS
                    if name not in ARCHITECTURAL_CHECKS
                )
        else:
            names.append(check)

    return sorted(set(names), key=lambda name: CHECK_LABELS.get(name, name).lower())


def render_lint_report(
    findings: list[LintFinding],
    *,
    models_checked: int,
    executed_checks: list[str] | None = None,
    console: Console | None = None,
    fail_level: Severity = "error",
    group_by: Literal["connascence", "model"] = "model",
) -> bool:
    """Render lint report. Returns True when findings are below fail_level."""
    console = console or Console()
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    has_errors = bool(errors)

    status = Text()
    if has_errors:
        status.append(f"{len(errors)} error{'s' if len(errors) != 1 else ''}", style="bold red")
    else:
        status.append("0 errors", style="bold green")
    status.append("  ·  ", style="dim")
    if warnings:
        status.append(
            f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}",
            style="bold yellow",
        )
    else:
        status.append("0 warnings", style="bold green")

    if has_errors:
        title = "[bold red]LINT FAILED[/bold red]"
        border_style = "red"
    elif warnings:
        title = "[bold yellow]LINT WARNINGS[/bold yellow]"
        border_style = "yellow"
    else:
        title = "[bold green]LINT PASSED[/bold green]"
        border_style = "green"

    console.print(
        Panel(
            Text.assemble(
                (f"{models_checked} models checked", "bold"),
                "\n",
                status,
            ),
            title=title,
            border_style=border_style,
            padding=(1, 2),
        )
    )

    by_check: dict[str, dict[Severity, int]] = defaultdict(
        lambda: {"error": 0, "warning": 0}
    )
    for finding in findings:
        by_check[finding.check][finding.severity] += 1

    console.print("\n[bold cyan]Issues by Check[/bold cyan]")
    summary = Table(
        box=box.SIMPLE,
        show_header=True,
        header_style="bold cyan",
        padding=(0, 2, 0, 0),
    )
    summary.add_column("Check", style="bold", no_wrap=True)
    summary.add_column("Errors", justify="right")
    summary.add_column("Warnings", justify="right")

    check_names = _summary_check_names(executed_checks, by_check)
    for check in check_names:
        counts = by_check.get(check, {"error": 0, "warning": 0})
        error_cell = (
            Text(str(counts["error"]), style="bold red")
            if counts["error"]
            else Text("·", style="dim")
        )
        warn_cell = (
            Text(str(counts["warning"]), style="bold yellow")
            if counts["warning"]
            else Text("·", style="dim")
        )
        summary.add_row(
            CHECK_LABELS.get(check, check),
            error_cell,
            warn_cell,
        )

    console.print(summary)

    if not findings:
        console.print("\n[bold green]All checks passed.[/bold green]")
        return True

    if group_by == "model":
        by_model: dict[str, list[LintFinding]] = defaultdict(list)
        repo_level: list[LintFinding] = []
        for finding in findings:
            if finding.model:
                by_model[normalize_model_name(finding.model)].append(finding)
            else:
                repo_level.append(finding)

        console.print("\n[bold cyan]Issues by Model[/bold cyan]")

        for model_name in sorted(by_model):
            model_findings = by_model[model_name]
            path = next((f.path for f in model_findings if f.path), None)
            header = f"[bold cyan]● {model_name}[/bold cyan]"
            if path:
                header += f" [dim]({path})[/dim]"
            console.print(header)

            table = Table(box=None, show_header=False, padding=0)
            table.add_column(width=4, no_wrap=True)
            table.add_column()

            for finding in sorted(model_findings, key=lambda f: (f.severity, f.check)):
                icon = "✘" if finding.severity == "error" else "⚠"
                style = "red" if finding.severity == "error" else "yellow"
                
                msg_text = Text()
                msg_lines = finding.message.split("\n")
                for i, line in enumerate(msg_lines):
                    if i > 0:
                        msg_text.append("\n")
                    msg_text.append(line)
                msg_text.append(" ")
                msg_text.append(f"({finding.check})", style="dim")
                
                table.add_row(f"  [{style}]{icon}[/{style}] ", msg_text)
            console.print(table)
            console.print()

        if repo_level:
            console.print("[bold cyan]Repository-level issues[/bold cyan]")
            table = Table(box=None, show_header=False, padding=0)
            table.add_column(width=4, no_wrap=True)
            table.add_column()
            for finding in repo_level:
                icon = "✘" if finding.severity == "error" else "⚠"
                style = "red" if finding.severity == "error" else "yellow"
                
                msg_text = Text()
                msg_lines = finding.message.split("\n")
                for i, line in enumerate(msg_lines):
                    if i > 0:
                        msg_text.append("\n")
                    msg_text.append(line)
                msg_text.append(" ")
                msg_text.append(f"({finding.check})", style="dim")
                
                table.add_row(f"  [{style}]{icon}[/{style}] ", msg_text)
            console.print(table)
            console.print()
    else:
        by_category: dict[str, list[LintFinding]] = defaultdict(list)
        for finding in findings:
            category = CONNASCENCE_CATEGORIES.get(finding.check, "Other Checks")
            by_category[category].append(finding)

        category_order = [
            "Connascence of Name (CoN)",
            "Connascence of Type (CoT)",
            "Connascence of Position (CoP)",
            "Connascence of Meaning (CoM)",
            "Dynamic Coupling & DAG Structure",
            "Quality & Metadata (Non-Connascence)",
            "Other Checks",
        ]

        console.print()

        for category in category_order:
            cat_findings = by_category.get(category)
            if not cat_findings:
                continue

            console.print(f"[bold cyan]● {category}[/bold cyan]")

            sorted_findings = sorted(
                cat_findings,
                key=lambda f: (
                    f.model or "",
                    f.severity,
                    f.check,
                ),
            )

            table = Table(box=None, show_header=False, padding=0)
            table.add_column(width=4, no_wrap=True)
            table.add_column()

            for finding in sorted_findings:
                icon = "✘" if finding.severity == "error" else "⚠"
                style = "red" if finding.severity == "error" else "yellow"

                if finding.model:
                    model_name = normalize_model_name(finding.model)
                    model_part = Text()
                    model_part.append(model_name, style="bold")
                    if finding.path:
                        model_part.append(f" ({finding.path})", style="dim")
                else:
                    model_part = Text("Repository-level", style="bold")

                cell_content = Text()
                cell_content.append(model_part)
                cell_content.append("\n")
                
                msg_text = Text()
                msg_lines = finding.message.split("\n")
                for i, line in enumerate(msg_lines):
                    if i > 0:
                        msg_text.append("\n")
                    msg_text.append(line)
                msg_text.append(" ")
                msg_text.append(f"({finding.check})", style="dim")
                
                cell_content.append(msg_text)

                table.add_row(f"  [{style}]{icon}[/{style}] ", cell_content)
            console.print(table)
            console.print()

    failed = any(f.severity == fail_level for f in findings)
    if fail_level == "error" and has_errors:
        console.print("[bold red]Lint failed — fix errors above before merging.[/bold red]")
    elif failed:
        console.print(
            "[bold red]Lint failed — fix findings above before merging.[/bold red]"
        )
    elif warnings:
        console.print(
            "[bold yellow]Lint passed with warnings — review before merging.[/bold yellow]"
        )

    return not failed
