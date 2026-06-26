"""Column data type requirements — configurable rules."""

from __future__ import annotations

import re
import typing as t

from sqlmesh.core.linter.rule import Rule, RuleViolation
from sqlmesh.core.model import Model

from sqlmesh_ff.context import get_ff_config
from sqlmesh_ff.utils.paths import get_layer_from_path


class ColumnTypes(Rule):
    """Column data type requirements from fitness_functions.yaml."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.column_types
        if not rule_config.enabled or not rule_config.rules:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        if not model.columns_to_types:
            return None

        equivalent_types = {
            key: set(values)
            for key, values in rule_config.equivalent_types.items()
        }

        violations = []
        for entry in rule_config.rules:
            pattern = entry.pattern
            expected_type_str = entry.data_type.lower()
            accepted_types = equivalent_types.get(
                expected_type_str, {expected_type_str}
            )
            for column_name, dtype in model.columns_to_types.items():
                if re.search(pattern, column_name):
                    actual_type_str = dtype.this.value.lower()
                    if (
                        actual_type_str not in accepted_types
                        and actual_type_str not in ("unknown", "null")
                    ):
                        violations.append(
                            f"Column '{column_name}' matched rule '{entry.name}' "
                            f"but has type '{actual_type_str}' instead of '{expected_type_str}'"
                        )
        if violations:
            return (
                self.violation(violations) if not model.kind.is_symbolic else None
            )
        return None
