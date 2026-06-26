"""Metadata fitness rules — owner, description, grain."""

from __future__ import annotations

import typing as t

from sqlmesh.core.linter.rule import Rule, RuleViolation
from sqlmesh.core.model import Model

from sqlmesh_ff.context import get_ff_config
from sqlmesh_ff.utils.paths import get_layer_from_path


class NoMissingOwner(Rule):
    """Model owner should always be specified."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.owner:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation() if not model.owner and not model.kind.is_symbolic else None
        )


class NoMissingDescription(Rule):
    """Model description should always be specified."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.description:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if not model.description and not model.kind.is_symbolic
            else None
        )


class NoMissingGrain(Rule):
    """Model grains should always be specified."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.grain:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if not model.grains and not model.kind.is_symbolic
            else None
        )


class NoMissingNotNull(Rule):
    """Model must have a not_null audit specified."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.not_null:
            return None
        if model.kind.is_external or model.kind.is_symbolic:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        has_not_null = any(name == "not_null" for name, _ in model.audits)
        return self.violation() if not has_not_null else None


class NoMissingUniqueValues(Rule):
    """Model must have a unique_values audit specified."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.unique_values:
            return None
        if model.kind.is_external or model.kind.is_symbolic:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        has_unique_values = any(name == "unique_values" for name, _ in model.audits)
        return self.violation() if not has_unique_values else None
