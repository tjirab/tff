"""Filename must match model name."""

from __future__ import annotations

from pathlib import Path

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config
from tff.core.utils.paths import get_layer_from_path


class FilenameEqualsModelname(Rule):
    """The filename should equal the model name."""
    name = "filenameequalsmodelname"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.filename_equals_modelname
        if not rule_config.enabled:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if (model.name.split(".")[-1] != Path(model.path).stem)
            and not model.is_symbolic
            else None
        )
