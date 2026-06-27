"""Rule to ban positional GROUP BY and ORDER BY integers."""

from __future__ import annotations

from pathlib import Path
import sqlglot
import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config
from tff.core.utils.paths import get_layer_from_path


class NoPositionalGroupByOrOrderBy(Rule):
    """Ensure GROUP BY and ORDER BY clauses reference column names, not positional integers."""
    name = "nopositionalgroupbyororderby"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.no_positional_group_by_or_order_by
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        path = Path(model.path)
        if not path.exists():
            return None

        try:
            sql = path.read_text(encoding="utf-8")
            # Strip SQLMesh MODEL block if present
            import re
            sql = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
            parsed = sqlglot.parse_one(sql, read=model.dialect)
        except Exception:
            return None

        violations = []
        
        group_by_count = 0
        for group in parsed.find_all(exp.Group):
            for expr in group.expressions:
                if isinstance(expr, exp.Literal) and expr.is_int:
                    group_by_count += 1
        if group_by_count > 0:
            suffix = "s" if group_by_count != 1 else ""
            violations.append(
                f"{group_by_count} positional GROUP BY reference{suffix} found. Use column name instead."
            )

        order_by_count = 0
        for order in parsed.find_all(exp.Order):
            for ordered in order.expressions:
                if isinstance(ordered.this, exp.Literal) and ordered.this.is_int:
                    order_by_count += 1
        if order_by_count > 0:
            suffix = "s" if order_by_count != 1 else ""
            violations.append(
                f"{order_by_count} positional ORDER BY reference{suffix} found. Use column name instead."
            )

        if violations:
            return self.violation(violations)
        return None
