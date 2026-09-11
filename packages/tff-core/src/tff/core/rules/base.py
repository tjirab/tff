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
        cfg = getattr(self, "_config", None)
        if cfg is None:
            from tff.core.config import FitnessFunctionsConfig

            cfg = FitnessFunctionsConfig()
            self._config = cfg
        return cfg

    @config.setter
    def config(self, value: FitnessFunctionsConfig | None) -> None:
        self._config = value

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        raise NotImplementedError()

    def violation(self, message: str | list[str] = "") -> RuleViolation:
        if not message:
            message = self.__doc__ or ""
        return RuleViolation(violation_msg=message)
