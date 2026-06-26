"""Connascence-of-meaning fitness function — require classification macros."""

from __future__ import annotations

import re
import typing as t
from pathlib import Path

from sqlmesh.core.linter.rule import Rule, RuleViolation
from sqlmesh.core.model import Model

from sqlmesh_ff.context import get_ff_config
from sqlmesh_ff.utils.paths import get_layer_from_path

MODEL_BLOCK_PATTERN = re.compile(r"^MODEL\s*\(.*?\)\s*;", re.DOTALL | re.IGNORECASE)


def strip_model_block(sql: str) -> str:
    return MODEL_BLOCK_PATTERN.sub("", sql).strip()


def _case_as_column_pattern(columns: dict[str, str]) -> re.Pattern[str]:
    column_names = "|".join(columns.keys())
    return re.compile(
        rf"CASE\b(?:(?!END\s+AS).)*END\s+AS\s+(?P<column>{column_names})\b",
        re.IGNORECASE | re.DOTALL,
    )


def find_classification_violations(
    sql: str, columns: dict[str, str]
) -> list[str]:
    violations: list[str] = []
    case_pattern = _case_as_column_pattern(columns)

    has_macro = {
        column: bool(re.search(macro_pattern, sql, re.IGNORECASE))
        for column, macro_pattern in columns.items()
    }

    for match in case_pattern.finditer(sql):
        column = match.group("column").lower()
        expression = match.group(0)
        macro_pattern = columns.get(column)
        if has_macro.get(column):
            continue
        if macro_pattern and not re.search(macro_pattern, expression, re.IGNORECASE):
            violations.append(
                f"Inline CASE defines '{column}' — use the @{column} macro instead"
            )

    return violations


class ClassificationMacros(Rule):
    """Classification columns must use macros in configured layers."""

    def check_model(self, model: Model) -> t.Optional[RuleViolation]:
        rule_config = get_ff_config().rules.classification_macros
        if not rule_config.enabled:
            return None

        if model.kind.is_symbolic:
            return None

        layer = get_layer_from_path(model._path)
        if not rule_config.should_run(layer):
            return None

        path = Path(model._path)
        if not path.exists():
            return None

        sql = strip_model_block(path.read_text(encoding="utf-8"))
        violations = find_classification_violations(sql, rule_config.columns)
        if violations:
            return self.violation(violations)
        return None
