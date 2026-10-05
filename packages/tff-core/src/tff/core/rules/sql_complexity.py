"""SQL complexity fitness function — warn when models exceed maintainability thresholds."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import sqlglot.expressions as exp
from sqlglot import parse_one

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation

if TYPE_CHECKING:
    from tff.core.report import Severity

MODEL_BLOCK_PATTERN = re.compile(r"^MODEL\s*\(.*?\)\s*;", re.DOTALL | re.IGNORECASE)


def strip_model_block(sql: str) -> str:
    return MODEL_BLOCK_PATTERN.sub("", sql).strip()


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
