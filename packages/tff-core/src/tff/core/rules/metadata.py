"""Metadata fitness rules — owner, description, grain."""

from __future__ import annotations

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config
from tff.core.utils.paths import get_layer_from_path


class NoMissingOwner(Rule):
    """Model owner should always be specified."""
    name = "nomissingowner"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.owner:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation() if not model.owner and not model.is_symbolic else None
        )


class NoMissingDescription(Rule):
    """Model description should always be specified."""
    name = "nomissingdescription"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.description:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if not model.description and not model.is_symbolic
            else None
        )


class NoMissingGrain(Rule):
    """Model grains should always be specified."""
    name = "nomissinggrain"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.grain:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if not model.grains and not model.is_symbolic
            else None
        )


class NoMissingNotNull(Rule):
    """Model must have a not_null audit specified."""
    name = "nomissingnotnull"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.not_null:
            return None
        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        has_not_null = any(name == "not_null" for name, _ in model.audits)
        return self.violation() if not has_not_null else None


class NoMissingUniqueValues(Rule):
    """Model must have a unique_values audit specified."""
    name = "nomissinguniquevalues"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.metadata
        if not rule_config.unique_values:
            return None
        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        has_unique_values = any(name == "unique_values" for name, _ in model.audits)
        return self.violation() if not has_unique_values else None
