"""Rule to ban positional GROUP BY integers."""

from __future__ import annotations

import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.utils.paths import get_layer_from_path


class NoPositionalGroupBy(Rule):
    """Ensure GROUP BY clauses reference column names, not positional integers."""

    name = "nopositionalgroupby"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.no_positional_group_by
        parent_config = self.config.rules.no_positional_group_by_or_order_by
        if not (rule_config.enabled and parent_config.enabled and parent_config.group_by):
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer) or not parent_config.should_run(layer):
            return None

        parsed = model.ast
        if parsed is None:
            return None

        group_by_count = 0
        for group in parsed.find_all(exp.Group):
            for expr in group.expressions:
                if isinstance(expr, exp.Literal) and expr.is_int:
                    group_by_count += 1
        if group_by_count > 0:
            suffix = "s" if group_by_count != 1 else ""
            return self.violation(
                [f"{group_by_count} positional GROUP BY reference{suffix} found. Use column name instead."]
            )
        return None
