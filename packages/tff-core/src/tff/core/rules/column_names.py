"""Column naming requirements — configurable replacements."""

from __future__ import annotations

import re

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.utils.paths import get_layer_from_path


class ColumnNames(Rule):
    """Column naming requirements from fitness_functions.yaml replacements map."""
    name = "columnnames"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.column_names
        if not rule_config.enabled or not rule_config.replacements:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        if not model.columns_to_types:
            return None

        violations = []
        for bad_pattern, good_pattern in rule_config.replacements.items():
            for column_name in model.columns_to_types:
                if re.search(bad_pattern, column_name):
                    suggestion = re.sub(bad_pattern, good_pattern, column_name)
                    violations.append(
                        f"Try changing '{column_name}' to '{suggestion}'."
                    )
        if violations:
            return (
                self.violation(violations) if not model.is_symbolic else None
            )
        return None
