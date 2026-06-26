"""Filename must match model name."""

from __future__ import annotations

import typing as t
from pathlib import Path

from sqlmesh.core.linter.rule import Rule, RuleViolation
from sqlmesh.core.model import Model

from sqlmesh_ff.context import get_ff_config
from sqlmesh_ff.utils.paths import get_layer_from_path


class FilenameEqualsModelname(Rule):
    """The filename should equal the model name."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.filename_equals_modelname
        if not rule_config.enabled:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if (model.name.split(".")[-1] != Path(model._path).stem)
            and not model.kind.is_symbolic
            else None
        )
