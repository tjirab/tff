"""Shared lint finding types and report rendering."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

from rich.console import Console
from rich.style import Style
from rich.text import Text

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
    link_url = Path(path).resolve().as_uri() if path else ""

    return Text(display, style=Style(link=link_url) if link_url else None)


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
    rule_def = registry.get(f.check)
    return bool(rule_def and rule_def.is_fixable) or f.check in (
        "filenameequalsmodelname",
        "filename_equals_modelname",
    )


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


class DisjointSet:
    """Disjoint-Set / Union-Find data structure with path compression and union by rank."""

    def __init__(self) -> None:
        self.parent: dict[Any, Any] = {}
        self.rank: dict[Any, int] = {}

    def find(self, item: Any) -> Any:
        if item not in self.parent:
            self.parent[item] = item
            self.rank[item] = 0
            return item
        root = item
        while self.parent[root] != root:
            root = self.parent[root]
        curr = item
        while curr != root:
            nxt = self.parent[curr]
            self.parent[curr] = root
            curr = nxt
        return root

    def union(self, item1: Any, item2: Any) -> Any:
        root1 = self.find(item1)
        root2 = self.find(item2)
        if root1 == root2:
            return root1
        if self.rank[root1] < self.rank[root2]:
            self.parent[root1] = root2
            return root2
        elif self.rank[root1] > self.rank[root2]:
            self.parent[root2] = root1
            return root1
        else:
            self.parent[root2] = root1
            self.rank[root1] += 1
            return root1


def group_findings_by_model(
    findings: Sequence[LintFinding],
) -> tuple[list[dict[str, Any]], list[LintFinding]]:
    """Group lint findings by model identity (name and/or path).

    Returns a tuple of (sorted_model_groups, repo_level_findings).
    """
    repo_level: list[LintFinding] = []
    finding_entries: list[tuple[Any, LintFinding]] = []
    dsu = DisjointSet()

    stem_to_items: dict[str, list[tuple[str, str]]] = defaultdict(list)
    qualified_to_items: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)

    for finding in findings:
        raw_model = finding.model or ""
        norm_name = normalize_model_name(raw_model) if raw_model else ""
        raw_path = finding.path or ""
        norm_path = raw_path.replace("\\", "/").strip() if raw_path else ""

        if not norm_name and not norm_path:
            repo_level.append(finding)
            continue

        path_node = ("path", norm_path) if norm_path else None
        name_node = ("name", norm_name) if norm_name else None

        if path_node and name_node:
            dsu.union(path_node, name_node)
            primary_node = path_node
        elif path_node:
            dsu.find(path_node)
            primary_node = path_node
        else:
            dsu.find(name_node)
            primary_node = name_node

        finding_entries.append((primary_node, finding))

        if norm_path:
            p = Path(norm_path)
            stem = p.stem
            stem_to_items[stem].append(path_node)
            parent_dir = p.parent.name
            if parent_dir:
                qualified_to_items[(parent_dir, stem)].append(path_node)

        if norm_name:
            parts = norm_name.split(".")
            stem = parts[-1]
            stem_to_items[stem].append(name_node)
            if len(parts) >= 2:
                qualified_to_items[(parts[-2], parts[-1])].append(name_node)

    # First pass: unify items sharing qualified (namespace/folder, stem) if no conflicting path roots
    for q_items in qualified_to_items.values():
        path_roots = {dsu.find(item) for item in q_items if item[0] == "path"}
        if len(path_roots) <= 1:
            first = q_items[0]
            for other in q_items[1:]:
                dsu.union(first, other)

    # Second pass: unify items sharing bare stem if no conflicting path roots or qualified names
    for s_items in stem_to_items.values():
        path_roots = {dsu.find(item) for item in s_items if item[0] == "path"}
        qualified_names = {
            item[1] for item in s_items if item[0] == "name" and "." in item[1]
        }
        if len(path_roots) <= 1 and len(qualified_names) <= 1:
            first = s_items[0]
            for other in s_items[1:]:
                dsu.union(first, other)

    # Aggregate findings and metadata by root component
    component_findings: dict[Any, list[LintFinding]] = defaultdict(list)
    component_names: dict[Any, set[str]] = defaultdict(set)
    component_paths: dict[Any, list[str]] = defaultdict(list)
    first_seen_name: dict[Any, str] = {}

    for primary_node, finding in finding_entries:
        root = dsu.find(primary_node)
        component_findings[root].append(finding)

        raw_model = finding.model or ""
        norm_name = normalize_model_name(raw_model) if raw_model else ""
        raw_path = finding.path or ""
        norm_path = raw_path.replace("\\", "/").strip() if raw_path else ""

        if norm_name:
            component_names[root].add(norm_name)
            if root not in first_seen_name:
                first_seen_name[root] = norm_name

        if norm_path and norm_path not in component_paths[root]:
            component_paths[root].append(norm_path)

    groups: list[dict[str, Any]] = []
    for root, group_findings in component_findings.items():
        names = component_names[root]
        paths = component_paths[root]
        primary_path = paths[0] if paths else None
        display_name = first_seen_name.get(root, "")

        if primary_path:
            stem = Path(primary_path).stem
            if stem in names or not display_name:
                display_name = stem

        groups.append(
            {
                "name": display_name,
                "path": primary_path,
                "names": names,
                "findings": group_findings,
            }
        )

    sorted_groups = sorted(
        groups,
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
    has_warnings = bool(warnings)

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
    failed = has_errors or (fail_level == "warning" and has_warnings)

    footer = Text()
    if has_errors:
        footer.append(f"FAIL — {len(errors)} error{'s' if len(errors) != 1 else ''} block merge.", style="bold red")
        if fixable_count > 0:
            footer.append(" Run `tff lint --fix` for auto-correctable rules.", style="bold")
    elif failed:
        footer.append(f"FAIL — {len(warnings)} warning{'s' if len(warnings) != 1 else ''} block merge.", style="bold red")
    else:
        footer.append(f"WARN — {len(warnings)} warning{'s' if len(warnings) != 1 else ''} found. Review before merge.", style="bold yellow")

    console.print(footer)

    complexity_findings = [
        f for f in findings if f.check in ("sqlcomplexity", "sql_complexity") and f.model
    ]
    if complexity_findings:
        m_name = normalize_model_name(complexity_findings[0].model)
        console.print(
            f"[dim]● Tip: Run 'tff explain sqlcomplexity --model {m_name}' to inspect decision points.[/dim]"
        )

    return not failed
