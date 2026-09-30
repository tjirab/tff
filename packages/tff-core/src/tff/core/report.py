"""Shared lint finding types and report rendering."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Sequence

from rich.console import Console
from rich.text import Text
from pathlib import Path

from tff.core.config import Severity
from tff.core.registry import registry


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

    return Text(display, style=f"link {link_url}" if link_url else None)


def _format_connascence_tag(category_str: str) -> str:
    cat_lower = category_str.lower()
    if "coupling" in cat_lower or "dag" in cat_lower or "dynamic" in cat_lower:
        return "dynamic"
    if "quality" in cat_lower or "metadata" in cat_lower:
        return "metadata"
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
    """Render lint report in architectural audit ledger format."""
    console = console or Console()
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]
    has_errors = bool(errors)

    width = min(console.width - 2, 86) if console.width else 78

    console.print("[bold]TFF ARCHITECTURE AUDIT[/bold]")
    summary_parts = [
        f"{models_checked} model{'s' if models_checked != 1 else ''}",
        f"{len(errors)} error{'s' if len(errors) != 1 else ''}",
        f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}",
    ]
    if duration is not None:
        summary_parts.append(f"{duration:.2f}s")
    console.print(" · ".join(summary_parts))
    console.print()

    if not findings:
        console.print("─" * width, style="dim")
        console.print("[bold green]PASS — all fitness functions satisfied.[/bold green]")
        return True

    loc_col = 8
    rule_col = 60 if width >= 84 else 46
    coup_col = 77 if width >= 84 else 65

    header_cols = Text()
    header_cols.append("STATUS  LOCATION", style="bold")
    header_cols.append(" " * max(2, rule_col - len("STATUS  LOCATION")))
    header_cols.append("RULE", style="bold")
    header_cols.append(" " * max(2, coup_col - rule_col - len("RULE")))
    header_cols.append("COUPLING", style="bold")
    console.print(header_cols)
    console.print("─" * width, style="dim")

    if group_by == "connascence":
        sorted_findings = sorted(
            findings,
            key=lambda f: (
                CONNASCENCE_CATEGORIES.get(f.check, "Other Checks"),
                0 if f.severity == "error" else 1,
                f.path or f.model or "",
            ),
        )
    else:
        sorted_findings = sorted(
            findings,
            key=lambda f: (
                f.path or (normalize_model_name(f.model) if f.model else "") or "zzz",
                0 if f.severity == "error" else 1,
                f.check,
            ),
        )

    for i, finding in enumerate(sorted_findings):
        if finding.severity == "error":
            status_tag = Text("ERR     ", style="bold red")
        else:
            status_tag = Text("WRN     ", style="bold yellow")

        if finding.path:
            if finding.line is not None:
                col_val = f":{finding.col}" if finding.col is not None else ":1"
                loc_str = f"{finding.path}:{finding.line}{col_val}"
            else:
                loc_str = finding.path
            loc_cell = _format_file_reference(finding.path, finding.line, display_text=loc_str)
        elif finding.model:
            loc_str = normalize_model_name(finding.model)
            loc_cell = Text(loc_str)
        else:
            loc_str = "project"
            loc_cell = Text(loc_str, style="dim")

        check_name = finding.check
        docs_url = registry.get_docs_url(check_name)
        rule_cell = Text(check_name, style=f"link {docs_url}" if docs_url else None)

        category = CONNASCENCE_CATEGORIES.get(check_name, "")
        coupling_str = _format_connascence_tag(category)

        row = Text()
        row.append_text(status_tag)
        row.append_text(loc_cell)
        pad_loc = max(2, (rule_col - loc_col) - len(loc_str))
        row.append(" " * pad_loc)
        row.append_text(rule_cell)
        pad_rule = max(2, (coup_col - rule_col) - len(check_name))
        row.append(" " * pad_rule)
        row.append(coupling_str, style="dim")
        console.print(row)

        # Message
        msg_lines = finding.message.split("\n")
        first_line = msg_lines[0]
        msg_prefix = Text("        ")
        if finding.severity == "error":
            msg_prefix.append("! ", style="bold red")
        else:
            msg_prefix.append("* ", style="bold yellow")
        msg_prefix.append(first_line)
        console.print(msg_prefix)

        for extra_line in msg_lines[1:]:
            extra_row = Text("          ")
            extra_row.append(extra_line)
            console.print(extra_row)

        if i < len(sorted_findings) - 1:
            console.print()

    console.print("─" * width, style="dim")

    fixable_count = sum(1 for f in findings if _is_fixable_finding(f))
    failed = any(f.severity == fail_level for f in findings)

    footer = Text()
    if has_errors:
        footer.append(f"FAIL — {len(errors)} error{'s' if len(errors) != 1 else ''} block merge.", style="bold red")
        if fixable_count > 0:
            footer.append(" Run `tff --fix` for auto-correctable rules.", style="bold")
    elif failed:
        footer.append(f"FAIL — {len(warnings)} warning{'s' if len(warnings) != 1 else ''} block merge.", style="bold red")
    else:
        footer.append(f"WARN — {len(warnings)} warning{'s' if len(warnings) != 1 else ''} found. Review before merge.", style="bold yellow")

    console.print(footer)
    return not failed
