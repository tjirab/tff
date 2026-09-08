from __future__ import annotations

import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation


@dataclass
class RuleViolation:
    violation_msg: str | list[str]


class Rule:
    name: str = ""

    def __init__(self, config: FitnessFunctionsConfig | None = None) -> None:
        self._config = config

    @property
    def config(self) -> FitnessFunctionsConfig:
        if self._config is not None:
            return self._config
        from tff.core.context import get_ff_config

        return get_ff_config()

    @config.setter
    def config(self, value: FitnessFunctionsConfig | None) -> None:
        self._config = value

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        raise NotImplementedError()

    def violation(self, message: str | list[str] = "") -> RuleViolation:
        if not message:
            message = self.__doc__ or ""
        return RuleViolation(violation_msg=message)
