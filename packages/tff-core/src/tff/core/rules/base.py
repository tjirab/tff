from __future__ import annotations

import typing as t
from dataclasses import dataclass

if t.TYPE_CHECKING:
    from tff.core.model import ModelRepresentation


@dataclass
class RuleViolation:
    violation_msg: str | list[str]


class Rule:
    name: str = ""

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        raise NotImplementedError()

    def violation(self, message: str | list[str] = "") -> RuleViolation:
        if not message:
            message = self.__doc__ or ""
        return RuleViolation(violation_msg=message)
