"""Rule to ban SELECT * expressions."""

from __future__ import annotations

import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config
from tff.core.utils.paths import get_layer_from_path


class BanSelectStar(Rule):
    """Ban SELECT * expressions in configured layers."""
    name = "banselectstar"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.ban_select_star
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        parsed = model.ast
        if parsed is None:
            return None

        violations = []
        for star in parsed.find_all(exp.Star):
            violations.append(
                "SELECT * is prohibited. Explicitly name your columns to reduce coupling."
            )

        if violations:
            return self.violation(violations)
        return None
