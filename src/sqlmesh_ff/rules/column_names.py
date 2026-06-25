"""Column naming requirements — configurable replacements."""

from __future__ import annotations

import re
import typing as t

from sqlmesh.core.linter.rule import Rule, RuleViolation
from sqlmesh.core.model import Model

from sqlmesh_ff.context import get_ff_config


class ColumnNames(Rule):
    """Column naming requirements from fitness_functions.yaml replacements map."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.column_names
        if not rule_config.enabled or not rule_config.replacements:
            return None

        if not model.columns_to_types:
            return None

        violations = []
        for bad_pattern, good_pattern in rule_config.replacements.items():
            for column_name in model.columns_to_types:
                if re.search(bad_pattern, column_name):
                    suggestion = column_name.replace(bad_pattern, good_pattern)
                    violations.append(
                        f"Try changing '{column_name}' to '{suggestion}'."
                    )
        if violations:
            return (
                self.violation(violations) if not model.kind.is_symbolic else None
            )
        return None
