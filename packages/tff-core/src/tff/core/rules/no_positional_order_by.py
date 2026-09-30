"""Rule to ban positional ORDER BY integers."""

from __future__ import annotations

import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.utils.paths import get_layer_from_path


class NoPositionalOrderBy(Rule):
    """Ensure ORDER BY clauses reference column names, not positional integers."""

    name = "nopositionalorderby"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.no_positional_order_by
        parent_config = self.config.rules.no_positional_group_by_or_order_by
        if not (rule_config.enabled and parent_config.enabled and parent_config.order_by):
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer) or not parent_config.should_run(layer):
            return None

        parsed = model.ast
        if parsed is None:
            return None

        order_by_count = 0
        for order in parsed.find_all(exp.Order):
            for ordered in order.expressions:
                if isinstance(ordered.this, exp.Literal) and ordered.this.is_int:
                    order_by_count += 1
        if order_by_count > 0:
            suffix = "s" if order_by_count != 1 else ""
            return self.violation(
                [f"{order_by_count} positional ORDER BY reference{suffix} found. Use column name instead."]
            )
        return None
