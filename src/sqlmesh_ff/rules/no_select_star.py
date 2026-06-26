"""Rule to ban SELECT * expressions."""

from __future__ import annotations

import typing as t

import sqlglot.expressions as exp
from sqlmesh.core.linter.rule import Rule, RuleViolation
from sqlmesh.core.model import Model

from sqlmesh_ff.context import get_ff_config
from sqlmesh_ff.utils.paths import get_layer_from_path


class NoSelectStar(Rule):
    """Ban SELECT * expressions in configured layers."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.no_select_star
        if not rule_config.enabled:
            return None

        if model.kind.is_symbolic or not model.query:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        violations = []
        for star in model.query.find_all(exp.Star):
            violations.append(
                "SELECT * is prohibited. Explicitly name your columns to reduce coupling."
            )

        if violations:
            return self.violation(violations)
        return None
