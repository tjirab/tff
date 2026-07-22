"""Mart model naming convention — configurable prefix rule."""

from __future__ import annotations

from pathlib import Path

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config


class MartModelNamingConvention(Rule):
    """Models in a mart layer subdirectory should start with the subdirectory name."""
    name = "martmodelnamingconvention"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.mart_naming
        if not rule_config.enabled:
            return None

        path = Path(model.path)
        parts = path.parts
        layer_name = rule_config.layer_name

        if layer_name not in parts:
            return None

        try:
            layer_index = parts.index(layer_name)
            mart_name = parts[layer_index + 1]
        except IndexError:
            return None

        if rule_config.rule != "prefix_with_subdirectory":
            return None

        model_name = path.stem
        if not model_name.startswith(f"{mart_name}_"):
            return self.violation(
                f"Model '{model_name}' in mart '{mart_name}' should start with '{mart_name}_'."
            )

        return None
