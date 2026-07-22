"""SQL complexity fitness function — warn when models exceed maintainability thresholds."""

from __future__ import annotations

import re
from pathlib import Path

import sqlglot.expressions as exp
from sqlglot import parse_one

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config

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
            if isinstance(parent, exp.From):
                return True
            parent = parent.parent
    return False


def analyze_sql(sql: str, dialect: str) -> dict[str, int | bool]:
    stripped = strip_model_block(sql)
    line_count = len([line for line in stripped.splitlines() if line.strip()])
    metrics: dict[str, int | bool] = {
        "line_count": line_count,
        "decision_points": 0,
        "cte_count": 0,
        "join_count": 0,
        "nested_subquery_in_final_select": False,
    }
    if not stripped:
        return metrics

    try:
        parsed = parse_one(stripped, read=dialect)
    except Exception:
        return metrics

    metrics["decision_points"] = count_decision_points(parsed)
    metrics["cte_count"] = count_ctes(parsed)
    metrics["join_count"] = count_joins(parsed)
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


class SqlComplexity(Rule):
    """Warn when SQL models exceed complexity thresholds (CTE/JOIN/decision points/lines)."""
    name = "sqlcomplexity"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.sql_complexity
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        from tff.core.utils.paths import get_layer_from_path

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        sql = model.query
        if sql is None:
            path = Path(model.path)
            if path.suffix != ".sql" or not path.exists():
                return None
            sql = path.read_text(encoding="utf-8")

        metrics = analyze_sql(sql, dialect=model.dialect)
        violations = format_violations(
            metrics, str(model.name), rule_config.thresholds
        )
        if violations:
            return self.violation(violations)
        return None
