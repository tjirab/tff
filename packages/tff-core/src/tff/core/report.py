"""Shared lint finding types and report rendering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pathlib import Path

from tff.core.registry import registry

Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class LintFinding:
    check: str
    severity: Severity
    message: str
    model: str | None = None
    path: str | None = None
    line: int | None = None


CHECK_LABELS: dict[str, str] = registry.get_check_labels()
CONNASCENCE_CATEGORIES: dict[str, str] = registry.get_connascence_categories()
ARCHITECTURAL_CHECKS: frozenset[str] = registry.get_architectural_check_names()
ALWAYS_VISIBLE_CHECKS: list[str] = [
    *ARCHITECTURAL_CHECKS,
    "sqlcomplexity",
    "classificationmacros",
]


def normalize_model_name(name: str) -> str:
    """Normalize model identifier for human-readable reporting.

    Strips quotes and dbt resource-type prefixes (e.g. 'model.pkg.name' -> 'name',
    'source.pkg.name' -> 'name'). For SQLMesh multi-part names (e.g. 'catalog.db.table'),
    preserves the standard two-part 'db.table' representation.
    """
    parts = name.replace('"', "").split(".")
    if parts and parts[0] in ("model", "seed", "source", "snapshot", "test"):
        return parts[-1]
    if len(parts) >= 2:
        return f"{parts[-2]}.{parts[-1]}"
    return name


def format_message(message: str | list[str]) -> str:
    if isinstance(message, list):
        return "; ".join(str(item) for item in message)
    return str(message)


def _format_check_cell(check: str) -> Text:
    label = CHECK_LABELS.get(check, check)
    docs_url = registry.get_docs_url(check)
    return (
        Text(label, style=f"bold link {docs_url}")
        if docs_url
        else Text(label, style="bold")
    )


def _format_file_reference(path: str, line: int | None = None) -> Text:
    """Format a file path with optional line number as a clickable terminal hyperlink.

    Produces ``path:line`` text wrapped in an OSC 8 ``file://`` hyperlink so that
    modern terminals (iTerm2, Ghostty, WezTerm, VS Code integrated terminal) allow
    ``Cmd+Click`` navigation directly to the source location.
    """
    display = path
    if line is not None:
        display = f"{path}:{line}"

    abs_path = str(Path(path).resolve())
    link_url = f"file://{abs_path}"

    return Text(display, style=f"dim link {link_url}")


def _append_check_tag(text: Text, check: str) -> None:
    docs_url = registry.get_docs_url(check)
    tag_style = f"dim link {docs_url}" if docs_url else "dim"
    text.append(f"({check})", style=tag_style)


def _summary_check_names(
    executed_checks: list[str] | None,
    by_check: dict[str, dict[Severity, int]],
) -> list[str]:
    if executed_checks is None:
        return sorted(set(ALWAYS_VISIBLE_CHECKS) | set(by_check))

    names: list[str] = []
    for check in executed_checks:
        if check in ("sqlmesh", "rules"):
            from_findings = {
                name for name in by_check if name not in ARCHITECTURAL_CHECKS
            }
            if from_findings:
                names.extend(from_findings)
            elif check == "sqlmesh":
                names.extend(
                    name
                    for name in ALWAYS_VISIBLE_CHECKS
                    if name not in ARCHITECTURAL_CHECKS
                )
            else:
                names.append("rules")
        else:
            names.append(check)

    if "rule_execution_error" in by_check:
        names.append("rule_execution_error")

    return sorted(set(names), key=lambda name: CHECK_LABELS.get(name, name).lower())


def render_lint_report(
    findings: list[LintFinding],
    *,
    models_checked: int,
    executed_checks: list[str] | None = None,
    console: Console | None = None,
    fail_level: Severity = "error",
    group_by: Literal["connascence", "model"] = "model",
    duration: float | None = None,
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

    summary_text = Text()
    summary_text.append(f"{models_checked} models checked", style="bold")
    if duration is not None:
        summary_text.append(f"  ·  {duration:.2f}s", style="dim")
    summary_text.append("\n")
    summary_text.append_text(status)

    console.print(
        Panel(
            summary_text,
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
            _format_check_cell(check),
            error_cell,
            warn_cell,
        )

    console.print(summary)

    if not findings:
        console.print("\n[bold green]All checks passed.[/bold green]")
        return True

    if group_by == "model":
        model_groups: dict[str, dict[str, Any]] = {}
        path_to_key: dict[str, str] = {}
        name_to_key: dict[str, str] = {}
        repo_level: list[LintFinding] = []

        for finding in findings:
            if not finding.model and not finding.path:
                repo_level.append(finding)
                continue

            raw_model = finding.model or ""
            norm_name = normalize_model_name(raw_model) if raw_model else ""
            raw_path = finding.path or ""
            norm_path = raw_path.replace("\\", "/").strip() if raw_path else ""

            target_key: str | None = None
            if norm_path and norm_path in path_to_key:
                target_key = path_to_key[norm_path]
            elif norm_name and norm_name in name_to_key:
                target_key = name_to_key[norm_name]
            elif norm_path:
                stem = Path(norm_path).stem
                if stem in name_to_key:
                    target_key = name_to_key[stem]

            if target_key is None:
                target_key = norm_path if norm_path else norm_name
                model_groups[target_key] = {
                    "name": norm_name,
                    "path": norm_path or None,
                    "names": {norm_name} if norm_name else set(),
                    "findings": [],
                }
                if norm_path:
                    path_to_key[norm_path] = target_key
                if norm_name:
                    name_to_key[norm_name] = target_key

            group = model_groups[target_key]
            group["findings"].append(finding)
            if norm_path and not group["path"]:
                group["path"] = norm_path
                path_to_key[norm_path] = target_key
            if norm_name:
                group["names"].add(norm_name)
                name_to_key[norm_name] = target_key

        console.print("\n[bold cyan]Issues by Model[/bold cyan]")

        # Determine canonical display name and sort
        for group in model_groups.values():
            if group["path"]:
                stem = Path(group["path"]).stem
                if stem in group["names"] or not group["name"]:
                    group["name"] = stem

        sorted_groups = sorted(
            model_groups.values(),
            key=lambda g: (g["name"] or "", g["path"] or ""),
        )

        for group in sorted_groups:
            model_name = group["name"]
            path = group["path"]
            header = Text()
            header.append(f"● {model_name}", style="bold cyan")
            if path:
                header.append(" (")
                header.append_text(_format_file_reference(path))
                header.append(")")
            console.print(header)

            table = Table(box=None, show_header=False, padding=0)
            table.add_column(width=4, no_wrap=True)
            table.add_column()

            for finding in sorted(group["findings"], key=lambda f: (f.severity, f.check)):
                icon = "✘" if finding.severity == "error" else "⚠"
                style = "red" if finding.severity == "error" else "yellow"
                
                msg_text = Text()
                if finding.line is not None and finding.path:
                    msg_text.append_text(_format_file_reference(finding.path, finding.line))
                    msg_text.append(" ")
                msg_lines = finding.message.split("\n")
                msg_text.append(msg_lines[0])
                msg_text.append(" ")
                _append_check_tag(msg_text, finding.check)
                for line in msg_lines[1:]:
                    msg_text.append("\n")
                    msg_text.append(line)
                
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
                msg_text.append(msg_lines[0])
                msg_text.append(" ")
                _append_check_tag(msg_text, finding.check)
                for line in msg_lines[1:]:
                    msg_text.append("\n")
                    msg_text.append(line)
                
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
            "Connascence of Algorithm (CoA)",
            "Connascence of Value (CoV)",
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
                        model_part.append(" (")
                        model_part.append_text(_format_file_reference(finding.path))
                        model_part.append(")")
                else:
                    model_part = Text("Repository-level", style="bold")

                cell_content = Text()
                cell_content.append(model_part)
                cell_content.append("\n")
                
                msg_text = Text()
                if finding.line is not None and finding.path:
                    msg_text.append_text(_format_file_reference(finding.path, finding.line))
                    msg_text.append(" ")
                msg_lines = finding.message.split("\n")
                msg_text.append(msg_lines[0])
                msg_text.append(" ")
                _append_check_tag(msg_text, finding.check)
                for line in msg_lines[1:]:
                    msg_text.append("\n")
                    msg_text.append(line)
                
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
