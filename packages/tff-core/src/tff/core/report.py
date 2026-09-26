"""Shared lint finding types and report rendering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal, Sequence

from rich.console import Console
from rich.panel import Panel
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
    col: int | None = None
    end_line: int | None = None
    end_col: int | None = None


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


def _format_file_reference(
    path: str,
    line: int | None = None,
    display_text: str | None = None,
) -> Text:
    """Format a file path with optional line number as a clickable terminal hyperlink.

    Produces ``path:line`` text (or custom ``display_text``) wrapped in an OSC 8
    ``file://`` hyperlink so that modern terminals allow ``Cmd+Click`` navigation.
    """
    display = display_text if display_text is not None else (f"{path}:{line}" if line is not None else path)
    abs_path = str(Path(path).resolve()) if path else ""
    link_url = f"file://{abs_path}" if abs_path else ""

    return Text(display, style=f"dim link {link_url}" if link_url else "dim")


def _format_connascence_tag(category_str: str) -> str:
    cat_lower = category_str.lower()
    if "name" in cat_lower:
        return "name"
    if "meaning" in cat_lower:
        return "meaning"
    if "algorithm" in cat_lower:
        return "algorithm"
    if "position" in cat_lower:
        return "position"
    if "value" in cat_lower:
        return "value"
    if "type" in cat_lower:
        return "type"
    if "coupling" in cat_lower or "dag" in cat_lower:
        return "dynamic coupling"
    if "quality" in cat_lower or "metadata" in cat_lower:
        return "quality"
    return category_str


def _is_fixable_finding(f: LintFinding) -> bool:
    if f.check in (
        "nopositionalgroupbyororderby",
        "nomissingdescription",
        "nomissingowner",
        "nomissingcolumns",
    ):
        return True
    if f.check == "sqlcomplexity" and "nested subquery in final SELECT" in f.message:
        return True
    return False


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


def group_findings_by_model(
    findings: Sequence[LintFinding],
) -> tuple[list[dict[str, Any]], list[LintFinding]]:
    """Group lint findings by model identity (name and/or path).

    Returns a tuple of (sorted_model_groups, repo_level_findings).
    """
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
                cand = name_to_key[stem]
                if not model_groups[cand]["path"] or model_groups[cand]["path"] == norm_path:
                    target_key = cand
        elif norm_name:
            stem = norm_name.split(".")[-1]
            if stem in name_to_key:
                cand = name_to_key[stem]
                if not norm_path or model_groups[cand]["path"] == norm_path:
                    target_key = cand

        # If this finding bridges two previously distinct groups, merge other_group into target_group
        if (
            target_key
            and norm_name
            and norm_name in name_to_key
            and name_to_key[norm_name] != target_key
        ):
            other_key = name_to_key[norm_name]
            other_group = model_groups.pop(other_key)
            target_group = model_groups[target_key]
            target_group["findings"].extend(other_group["findings"])
            target_group["names"].update(other_group["names"])
            if not target_group["name"] and other_group.get("name"):
                target_group["name"] = other_group["name"]
            if other_group.get("path"):
                target_group["path"] = other_group["path"]

            # Re-point all name and path lookups from other_key to target_key
            for n, k in list(name_to_key.items()):
                if k == other_key:
                    name_to_key[n] = target_key
            for p, k in list(path_to_key.items()):
                if k == other_key:
                    path_to_key[p] = target_key

        if target_key is None:
            target_key = norm_path if norm_path else norm_name
            model_groups[target_key] = {
                "name": norm_name,
                "path": norm_path or None,
                "names": {norm_name} if norm_name else set(),
                "findings": [],
            }

        group = model_groups[target_key]
        group["findings"].append(finding)
        if norm_path:
            if not group["path"]:
                group["path"] = norm_path
            path_to_key[norm_path] = target_key
            stem = Path(norm_path).stem
            if stem not in name_to_key:
                name_to_key[stem] = target_key
        if norm_name:
            group["names"].add(norm_name)
            name_to_key[norm_name] = target_key
            if not group["name"]:
                group["name"] = norm_name
            stem = norm_name.split(".")[-1]
            if stem not in name_to_key:
                name_to_key[stem] = target_key

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
    return sorted_groups, repo_level


def render_lint_report(
    findings: list[LintFinding],
    *,
    models_checked: int,
    executed_checks: list[str] | None = None,
    console: Console | None = None,
    fail_level: Severity = "error",
    group_by: Literal["connascence", "model"] = "model",
    duration: float | None = None,
    provider: str | None = None,
    dialect: str | None = None,
) -> bool:
    """Render lint report with tree-structured findings hierarchy."""
    console = console or Console()
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    has_errors = bool(errors)

    if has_errors:
        title = "[bold red]Findings Summary · LINT FAILED[/bold red]"
        border_style = "red"
    elif warnings:
        title = "[bold yellow]Findings Summary · LINT WARNINGS[/bold yellow]"
        border_style = "yellow"
    else:
        title = "[bold green]Findings Summary · LINT PASSED[/bold green]"
        border_style = "green"

    summary_text = Text()
    summary_text.append(f"{models_checked} models checked", style="bold")
    summary_text.append("  ·  ", style="dim")
    if findings:
        summary_text.append(
            f"{len(findings)} issue{'s' if len(findings) != 1 else ''} ({len(errors)} error{'s' if len(errors) != 1 else ''}, {len(warnings)} warning{'s' if len(warnings) != 1 else ''})"
        )
    else:
        summary_text.append("0 issues (0 errors, 0 warnings)", style="bold green")

    if duration is not None:
        summary_text.append("  ·  ", style="dim")
        summary_text.append(f"{duration:.2f}s", style="dim")

    console.print(
        Panel(
            summary_text,
            title=title,
            border_style=border_style,
            padding=(1, 2),
        )
    )

    if not findings:
        console.print("\n[bold green]All checks passed.[/bold green]")
        return True

    if group_by == "model":
        sorted_groups, repo_level = group_findings_by_model(findings)

        console.print("\n[bold cyan]Issues by Model[/bold cyan]")

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
            console.print("  │", style="dim")

            sorted_group_findings = sorted(
                group["findings"], key=lambda f: (f.severity, f.check)
            )
            total_in_group = len(sorted_group_findings)

            for idx, finding in enumerate(sorted_group_findings):
                is_last = idx == total_in_group - 1
                branch = "  └─ " if is_last else "  ├─ "
                continuation = "     " if is_last else "  │  "

                # Coordinate
                if finding.line is not None:
                    if finding.col is not None:
                        coord_str = f"{finding.line}:{finding.col}"
                    else:
                        coord_str = f"{finding.line}:1"
                    coord_text = _format_file_reference(
                        finding.path or "", finding.line, display_text=coord_str
                    )
                else:
                    coord_text = Text("──", style="dim")

                padded_coord = Text()
                padded_coord.append_text(coord_text)
                pad_len = max(0, 6 - len(coord_text.plain))
                padded_coord.append(" " * pad_len)

                if finding.severity == "error":
                    sev_tag = Text("error   ", style="bold red")
                else:
                    sev_tag = Text("warning ", style="bold yellow")

                msg_lines = finding.message.split("\n")
                first_line = msg_lines[0]

                row = Text()
                row.append(branch, style="dim")
                row.append_text(padded_coord)
                row.append(" ")
                row.append_text(sev_tag)
                row.append(first_line)
                console.print(row)

                for extra_line in msg_lines[1:]:
                    extra_text = Text()
                    extra_text.append(continuation + " " * 16, style="dim")
                    extra_text.append(extra_line)
                    console.print(extra_text)

                meta = Text()
                meta.append(continuation + " " * 16, style="dim")
                meta.append("rule: ", style="dim")
                rule_label = CHECK_LABELS.get(finding.check, finding.check)
                docs_url = registry.get_docs_url(finding.check)
                if docs_url:
                    meta.append(rule_label, style=f"dim link {docs_url}")
                else:
                    meta.append(rule_label, style="dim")
                meta.append(
                    f" ({finding.check})",
                    style=f"dim link {docs_url}" if docs_url else "dim",
                )

                category = CONNASCENCE_CATEGORIES.get(finding.check)
                if category:
                    meta.append("  ·  ", style="dim")
                    meta.append(
                        f"connascence: {_format_connascence_tag(category)}", style="dim"
                    )
                console.print(meta)

                if not is_last:
                    console.print("  │", style="dim")

            console.print()

        if repo_level:
            console.print("[bold cyan]Repository-level issues[/bold cyan]")
            console.print("  │", style="dim")
            for idx, finding in enumerate(repo_level):
                is_last = idx == len(repo_level) - 1
                branch = "  └─ " if is_last else "  ├─ "
                continuation = "     " if is_last else "  │  "

                coord_text = Text("──    ", style="dim")
                if finding.severity == "error":
                    sev_tag = Text("error   ", style="bold red")
                else:
                    sev_tag = Text("warning ", style="bold yellow")

                msg_lines = finding.message.split("\n")
                row = Text()
                row.append(branch, style="dim")
                row.append_text(coord_text)
                row.append(" ")
                row.append_text(sev_tag)
                row.append(msg_lines[0])
                row.append(" ")
                _append_check_tag(row, finding.check)
                console.print(row)

                for extra_line in msg_lines[1:]:
                    extra_text = Text()
                    extra_text.append(continuation + " " * 16, style="dim")
                    extra_text.append(extra_line)
                    console.print(extra_text)

                meta = Text()
                meta.append(continuation + " " * 16, style="dim")
                meta.append("rule: ", style="dim")
                rule_label = CHECK_LABELS.get(finding.check, finding.check)
                docs_url = registry.get_docs_url(finding.check)
                if docs_url:
                    meta.append(rule_label, style=f"dim link {docs_url}")
                else:
                    meta.append(rule_label, style="dim")
                meta.append(
                    f" ({finding.check})",
                    style=f"dim link {docs_url}" if docs_url else "dim",
                )

                category = CONNASCENCE_CATEGORIES.get(finding.check)
                if category:
                    meta.append("  ·  ", style="dim")
                    meta.append(
                        f"connascence: {_format_connascence_tag(category)}", style="dim"
                    )
                console.print(meta)

                if not is_last:
                    console.print("  │", style="dim")
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
            console.print("  │", style="dim")

            sorted_findings = sorted(
                cat_findings,
                key=lambda f: (
                    f.model or "",
                    f.severity,
                    f.check,
                ),
            )

            total_cat = len(sorted_findings)
            for idx, finding in enumerate(sorted_findings):
                is_last = idx == total_cat - 1
                branch = "  └─ " if is_last else "  ├─ "
                continuation = "     " if is_last else "  │  "

                if finding.path:
                    coord_str = (
                        f"{finding.path}:{finding.line}"
                        if finding.line is not None
                        else finding.path
                    )
                    coord_text = _format_file_reference(
                        finding.path, finding.line, display_text=coord_str
                    )
                elif finding.model:
                    coord_text = Text(normalize_model_name(finding.model), style="bold")
                else:
                    coord_text = Text("Repository-level", style="bold")

                if finding.severity == "error":
                    sev_tag = Text("error   ", style="bold red")
                else:
                    sev_tag = Text("warning ", style="bold yellow")

                msg_lines = finding.message.split("\n")
                row = Text()
                row.append(branch, style="dim")
                row.append_text(coord_text)
                row.append("  ")
                row.append_text(sev_tag)
                row.append(msg_lines[0])
                row.append(" ")
                _append_check_tag(row, finding.check)
                console.print(row)

                for extra_line in msg_lines[1:]:
                    extra_text = Text()
                    extra_text.append(continuation + " " * 8, style="dim")
                    extra_text.append(extra_line)
                    console.print(extra_text)

                meta = Text()
                meta.append(continuation + " " * 8, style="dim")
                meta.append("rule: ", style="dim")
                rule_label = CHECK_LABELS.get(finding.check, finding.check)
                docs_url = registry.get_docs_url(finding.check)
                if docs_url:
                    meta.append(rule_label, style=f"dim link {docs_url}")
                else:
                    meta.append(rule_label, style="dim")
                meta.append(
                    f" ({finding.check})",
                    style=f"dim link {docs_url}" if docs_url else "dim",
                )
                if finding.model:
                    meta.append("  ·  ", style="dim")
                    meta.append(
                        f"model: {normalize_model_name(finding.model)}", style="dim"
                    )
                console.print(meta)

                if not is_last:
                    console.print("  │", style="dim")
            console.print()

    files_with_findings = {f.path for f in findings if f.path}
    file_count = len(files_with_findings)
    fixable_count = sum(1 for f in findings if _is_fixable_finding(f))

    width = min(console.width - 2, 78) if console.width else 78
    console.print("  " + "─" * width, style="dim")

    summary_footer = Text("  ")
    if errors:
        summary_footer.append("✖ ", style="bold red")
        summary_footer.append(
            f"{len(errors)} error{'s' if len(errors) != 1 else ''}", style="bold red"
        )
    else:
        summary_footer.append("✔ 0 errors", style="bold green")

    if warnings:
        summary_footer.append(
            f", {len(warnings)} warning{'s' if len(warnings) != 1 else ''}",
            style="bold yellow",
        )

    if file_count > 0:
        summary_footer.append(f" in {file_count} file{'s' if file_count != 1 else ''}")
    console.print(summary_footer)

    if fixable_count > 0:
        fix_hint = Text("  ")
        fix_hint.append("ℹ ", style="bold cyan")
        fix_hint.append(
            f"{fixable_count} issue{'s' if fixable_count != 1 else ''} fixable automatically with ",
            style="dim",
        )
        fix_hint.append("`tff check --fix`", style="bold")
        console.print(fix_hint)

    failed = any(f.severity == fail_level for f in findings)
    if fail_level == "error" and has_errors:
        console.print(
            "[bold red]Lint failed — fix errors above before merging.[/bold red]"
        )
    elif failed:
        console.print(
            "[bold red]Lint failed — fix findings above before merging.[/bold red]"
        )
    elif warnings:
        console.print(
            "[bold yellow]Lint passed with warnings — review before merging.[/bold yellow]"
        )

    return not failed
