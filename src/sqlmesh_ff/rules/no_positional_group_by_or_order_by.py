"""Rule to ban positional GROUP BY and ORDER BY integers."""

from __future__ import annotations

import typing as t

import sqlglot.expressions as exp
from sqlmesh.core.linter.rule import Rule, RuleViolation
from sqlmesh.core.model import Model

from sqlmesh_ff.context import get_ff_config
from sqlmesh_ff.utils.paths import get_layer_from_path


class NoPositionalGroupByOrOrderBy(Rule):
    """Ensure GROUP BY and ORDER BY clauses reference column names, not positional integers."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.no_positional_group_by_or_order_by
        if not rule_config.enabled:
            return None

        if model.kind.is_symbolic or not model.query:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        violations = []
        
        group_by_count = 0
        for group in model.query.find_all(exp.Group):
            for expr in group.expressions:
                if isinstance(expr, exp.Literal) and expr.is_int:
                    group_by_count += 1
        if group_by_count > 0:
            suffix = "s" if group_by_count != 1 else ""
            violations.append(
                f"{group_by_count} positional GROUP BY reference{suffix} found. Use column name instead."
            )

        order_by_count = 0
        for order in model.query.find_all(exp.Order):
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
