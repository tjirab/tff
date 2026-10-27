"""SQL complexity fitness function — warn when models exceed maintainability thresholds."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any

import sqlglot.expressions as exp
from sqlglot import parse_one

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation

if TYPE_CHECKING:
    from tff.core.report import Severity

MODEL_BLOCK_PATTERN = re.compile(r"^MODEL\s*\(.*?\)\s*;", re.DOTALL | re.IGNORECASE)


@dataclass
class DecisionPointDetail:
    """Detailed record of a single cyclomatic decision point."""

    kind: str  # 'case', 'when', 'if', 'where_and', 'where_or'
    line: int | None
    col: int | None
    snippet: str
    cte_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "line": self.line,
            "col": self.col,
            "snippet": self.snippet,
            "cte_name": self.cte_name,
        }


@dataclass
class CteDetail:
    """Record of a Common Table Expression in the model."""

    name: str
    line: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "line": self.line,
        }


@dataclass
class JoinDetail:
    """Record of a JOIN expression in the model."""

    kind: str
    table: str
    line: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "table": self.table,
            "line": self.line,
        }


@dataclass
class ComplexityInspection:
    """Complete diagnostic inspection of model complexity and decision points."""

    model_name: str
    path: str | None
    dialect: str
    metrics: dict[str, int | bool]
    thresholds: dict[str, list[int]]
    decision_points: list[DecisionPointDetail]
    ctes: list[CteDetail]
    joins: list[JoinDetail]
    nested_subquery: bool
    recommendations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "path": self.path,
            "dialect": self.dialect,
            "metrics": self.metrics,
            "thresholds": self.thresholds,
            "decision_points": [dp.to_dict() for dp in self.decision_points],
            "ctes": [c.to_dict() for c in self.ctes],
            "joins": [j.to_dict() for j in self.joins],
            "nested_subquery": self.nested_subquery,
            "recommendations": self.recommendations,
        }


def strip_model_block(sql: str) -> str:
    return MODEL_BLOCK_PATTERN.sub("", sql).strip()


def _extract_node_line_col(node: exp.Expression) -> tuple[int | None, int | None]:
    """Find the earliest line and column coordinates from an AST node or its leaf tokens."""
    meta = getattr(node, "meta", None)
    if isinstance(meta, dict) and "line" in meta:
        return meta.get("line"), meta.get("col")

    best_pos: tuple[int, int] | None = None
    for child in node.walk():
        m = getattr(child, "meta", None)
        if isinstance(m, dict) and "line" in m:
            pos = (m["line"], m.get("col", 0))
            if best_pos is None or pos < best_pos:
                best_pos = pos
    if best_pos is not None:
        return best_pos[0], best_pos[1]
    return None, None


def count_decision_points(expression: exp.Expression) -> int:
    count = 0
    for node in expression.walk():
        if isinstance(node, (exp.Case, exp.If)):
            count += 1
        elif isinstance(node, exp.Where):
            count += _count_boolean_branches(node.this)
    return count


def _count_boolean_branches(expression: exp.Expression | None) -> int:
    if expression is None:
        return 0
    count = 0
    for node in expression.walk():
        if isinstance(node, (exp.And, exp.Or)):
            count += 1
    return count


def count_ctes(expression: exp.Expression) -> int:
    return sum(1 for node in expression.walk() if isinstance(node, exp.CTE))


def count_joins(expression: exp.Expression) -> int:
    return sum(1 for node in expression.walk() if isinstance(node, exp.Join))


def has_nested_subquery_in_final_select(expression: exp.Expression) -> bool:
    final_select = expression
    if isinstance(expression, exp.With):
        final_select = expression.this
    if not isinstance(final_select, exp.Select):
        return False
    for node in final_select.find_all(exp.Subquery):
        parent = node.parent
        while parent and parent is not final_select:
            if (
                isinstance(parent, (exp.From, exp.Join))
                and parent.parent is final_select
            ):
                return True
            parent = parent.parent
    return False


def _collect_ast_metrics(expression: exp.Expression) -> tuple[int, int, int]:
    """Collect decision points, CTE counts, and Join counts in a single AST traversal."""
    decision_points = 0
    cte_count = 0
    join_count = 0
    for node in expression.walk():
        if isinstance(node, (exp.Case, exp.If)):
            decision_points += 1
        elif isinstance(node, exp.Where):
            decision_points += _count_boolean_branches(node.this)
        elif isinstance(node, exp.CTE):
            cte_count += 1
        elif isinstance(node, exp.Join):
            join_count += 1
    return decision_points, cte_count, join_count


def analyze_sql(
    sql: str,
    dialect: str,
    parsed: exp.Expression | None = None,
) -> dict[str, int | bool]:
    stripped = strip_model_block(sql)
    line_count = len([line for line in stripped.splitlines() if line.strip()])
    metrics: dict[str, int | bool] = {
        "line_count": line_count,
        "decision_points": 0,
        "cte_count": 0,
        "join_count": 0,
        "nested_subquery_in_final_select": False,
    }
    if parsed is None:
        if not stripped:
            return metrics
        try:
            parsed = parse_one(stripped, read=dialect)
        except Exception:
            return metrics

    d_points, c_count, j_count = _collect_ast_metrics(parsed)
    metrics["decision_points"] = d_points
    metrics["cte_count"] = c_count
    metrics["join_count"] = j_count
    metrics["nested_subquery_in_final_select"] = has_nested_subquery_in_final_select(
        parsed
    )
    return metrics


def format_violations(
    metrics: dict[str, int | bool],
    model_name: str,
    thresholds: dict[str, list[int]],
) -> list[str]:
    messages: list[str] = []
    for metric, (warn_at, fail_at) in thresholds.items():
        value = metrics.get(metric, 0)
        if not isinstance(value, int):
            continue
        if value > warn_at:
            level = "FAIL" if value > fail_at else "WARN"
            messages.append(
                f"{level}: {metric}={value} (warn>{warn_at}, fail>{fail_at})"
            )
    if metrics.get("nested_subquery_in_final_select"):
        messages.append(
            "WARN: nested subquery in final SELECT — prefer CTEs per style guide"
        )
    if messages:
        return [f"{model_name}: " + "; ".join(messages)]
    return []


def inspect_sql_complexity(
    sql: str,
    dialect: str = "duckdb",
    model_name: str = "",
    path: str | None = None,
    thresholds: dict[str, list[int]] | None = None,
    parsed: exp.Expression | None = None,
) -> ComplexityInspection:
    """Analyze and inspect detailed SQL complexity metrics and decision points.

    Tracks cyclomatic decision points (CASE, WHEN, IF, WHERE AND/OR), CTEs,
    and JOIN operations with line numbers and source snippets.
    """
    from tff.core.config import DEFAULT_SQL_COMPLEXITY_THRESHOLDS

    thresholds = {**DEFAULT_SQL_COMPLEXITY_THRESHOLDS, **(thresholds or {})}

    # If SQL has a MODEL (...) block, preserve line count with newlines
    preserved_sql = MODEL_BLOCK_PATTERN.sub(
        lambda m: "\n" * m.group(0).count("\n"), sql
    )
    sql_lines = sql.splitlines()

    metrics = analyze_sql(sql, dialect=dialect, parsed=parsed)

    if parsed is None:
        stripped = preserved_sql.strip()
        if stripped:
            try:
                parsed = parse_one(preserved_sql, read=dialect)
            except Exception:
                try:
                    parsed = parse_one(preserved_sql)
                except Exception:
                    parsed = None

    decision_points: list[DecisionPointDetail] = []
    ctes: list[CteDetail] = []
    joins: list[JoinDetail] = []
    nested_subquery = bool(metrics.get("nested_subquery_in_final_select", False))

    if parsed is not None:
        # 1. Decision Points
        for node in parsed.walk():
            cte_ancestor = node.find_ancestor(exp.CTE)
            cte_name = cte_ancestor.alias_or_name if cte_ancestor else None

            if isinstance(node, exp.Case):
                first_line, col = _extract_node_line_col(node)
                case_line = first_line
                if (
                    first_line
                    and first_line > 1
                    and 0 < first_line - 1 <= len(sql_lines)
                    and "case" in sql_lines[first_line - 2].lower()
                ):
                    case_line = first_line - 1
                snip = (
                    sql_lines[case_line - 1].strip()
                    if case_line and 0 < case_line <= len(sql_lines)
                    else node.sql()[:50]
                )
                decision_points.append(
                    DecisionPointDetail(
                        kind="case",
                        line=case_line,
                        col=col,
                        snippet=snip,
                        cte_name=cte_name,
                    )
                )
            elif isinstance(node, exp.If):
                dp_line, dp_col = _extract_node_line_col(node)
                kind = "when" if isinstance(node.parent, exp.Case) else "if"
                snip = (
                    sql_lines[dp_line - 1].strip()
                    if dp_line and 0 < dp_line <= len(sql_lines)
                    else node.sql()[:50]
                )
                decision_points.append(
                    DecisionPointDetail(
                        kind=kind,
                        line=dp_line,
                        col=dp_col,
                        snippet=snip,
                        cte_name=cte_name,
                    )
                )
            elif isinstance(node, exp.Where):
                for b in node.this.walk():
                    if isinstance(b, (exp.And, exp.Or)):
                        rhs = getattr(b, "expression", None)
                        rhs_line, rhs_col = (
                            _extract_node_line_col(rhs) if rhs is not None else (None, None)
                        )
                        kind = "where_and" if isinstance(b, exp.And) else "where_or"
                        snip = (
                            sql_lines[rhs_line - 1].strip()
                            if rhs_line and 0 < rhs_line <= len(sql_lines)
                            else b.sql()[:50]
                        )
                        decision_points.append(
                            DecisionPointDetail(
                                kind=kind,
                                line=rhs_line,
                                col=rhs_col,
                                snippet=snip,
                                cte_name=cte_name,
                            )
                        )

        # 2. CTEs
        for cte in parsed.find_all(exp.CTE):
            cte_l, _ = _extract_node_line_col(cte)
            ctes.append(CteDetail(name=cte.alias_or_name, line=cte_l))

        # 3. Joins
        for join in parsed.find_all(exp.Join):
            kind_str = join.side or ""
            if join.kind:
                kind_str = f"{kind_str} {join.kind}".strip()
            if not kind_str:
                kind_str = "JOIN"
            table_name = join.this.sql() if join.this else ""
            join_l, _ = _extract_node_line_col(join)
            joins.append(
                JoinDetail(kind=kind_str.upper(), table=table_name, line=join_l)
            )

    # Sort decision points chronologically by line number
    decision_points.sort(key=lambda dp: (dp.line or float("inf"), dp.col or 0))

    # Recommendations
    recommendations: list[str] = []
    dp_threshold = thresholds.get("decision_points", DEFAULT_SQL_COMPLEXITY_THRESHOLDS["decision_points"])
    cte_threshold = thresholds.get("cte_count", DEFAULT_SQL_COMPLEXITY_THRESHOLDS["cte_count"])
    join_threshold = thresholds.get("join_count", DEFAULT_SQL_COMPLEXITY_THRESHOLDS["join_count"])
    line_threshold = thresholds.get("line_count", DEFAULT_SQL_COMPLEXITY_THRESHOLDS["line_count"])

    dp_count = int(metrics.get("decision_points", 0))
    if dp_count > dp_threshold[0]:
        case_when_count = sum(
            1 for dp in decision_points if dp.kind in ("case", "when", "if")
        )
        where_count = sum(
            1 for dp in decision_points if dp.kind in ("where_and", "where_or")
        )
        if case_when_count > 0:
            recommendations.append(
                f"Model has {case_when_count} CASE/IF decision branch{'es' if case_when_count != 1 else ''}. "
                "Consider extracting conditional mapping into seed lookup tables, dimension enums, or classification macros."
            )
        if where_count > 0:
            recommendations.append(
                f"Model has {where_count} boolean filter condition{'s' if where_count != 1 else ''} in WHERE clauses. "
                "Consider decomposing filter predicates into upstream CTEs or intermediate staging layers."
            )

    cte_cnt = int(metrics.get("cte_count", 0))
    if cte_cnt > cte_threshold[0]:
        recommendations.append(
            f"Model defines {cte_cnt} CTEs (warn>{cte_threshold[0]}, fail>{cte_threshold[1]}). "
            "Consider breaking down this complex transformation into multiple intermediate staging models."
        )

    join_cnt = int(metrics.get("join_count", 0))
    if join_cnt > join_threshold[0]:
        recommendations.append(
            f"Model executes {join_cnt} JOINs (warn>{join_threshold[0]}, fail>{join_threshold[1]}). "
            "Consider reviewing upstream marts or pre-joining relations in an intermediate layer."
        )

    if nested_subquery:
        recommendations.append(
            "Final SELECT contains nested subqueries. Prefer CTEs per project style guide to enhance readability and maintainability."
        )

    line_cnt = int(metrics.get("line_count", 0))
    if line_cnt > line_threshold[0]:
        recommendations.append(
            f"Model spans {line_cnt} lines (warn>{line_threshold[0]}, fail>{line_threshold[1]}). "
            "Consider modularizing into smaller, single-responsibility models."
        )

    if not recommendations:
        recommendations.append("Model is within all maintainability thresholds.")

    return ComplexityInspection(
        model_name=model_name,
        path=path,
        dialect=dialect,
        metrics=metrics,
        thresholds=thresholds,
        decision_points=decision_points,
        ctes=ctes,
        joins=joins,
        nested_subquery=nested_subquery,
        recommendations=recommendations,
    )



def split_complexity_message(
    message: str,
    base_severity: Severity | str = "error",
    model_name: str | None = None,
) -> list[tuple[str, Severity]]:
    """Split a semicolon-delimited complexity violation message into (part, severity) pairs."""
    if model_name:
        prefix = f"{model_name}: "
        if message.startswith(prefix):
            message = message[len(prefix) :]
    elif ": " in message and not (message.startswith("WARN:") or message.startswith("FAIL:")):
        _, rest = message.split(": ", 1)
        if rest.startswith("WARN:") or rest.startswith("FAIL:"):
            message = rest

    parts = [p.strip() for p in message.split(";") if p.strip()]
    findings: list[tuple[str, Severity]] = []
    for part in parts:
        if part.startswith("WARN:"):
            part_severity: Severity = "warning"
        elif part.startswith("FAIL:"):
            part_severity = "error" if base_severity == "error" else "warning"
        else:
            part_severity = "warning" if base_severity == "warning" else "error"
        findings.append((part, part_severity))
    return findings


parse_complexity_findings = split_complexity_message


class SqlComplexity(Rule):
    """Warn when SQL models exceed complexity thresholds (CTE/JOIN/decision points/lines)."""

    name = "sqlcomplexity"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.sql_complexity
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        from tff.core.utils.paths import get_layer_from_path

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        sql = model.get_sql()
        if sql is None:
            return None

        metrics = analyze_sql(sql, dialect=model.dialect, parsed=model.ast)
        violations = format_violations(
            metrics,
            str(model.name),
            rule_config.thresholds,
        )
        if violations:
            return self.violation(violations)
        return None
