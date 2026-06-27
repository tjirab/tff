"""Shared utilities for cross-model schema contract checks."""

from __future__ import annotations

import re
from pathlib import Path


def extract_final_select_columns(sql: str) -> list[str]:
    """Extract column names/aliases from the final SELECT statement."""
    last_select_match = None
    for match in re.finditer(r"(?:^|\n)SELECT\b", sql, re.IGNORECASE):
        last_select_match = match

    if not last_select_match:
        return []

    select_body = sql[last_select_match.end() :]
    from_match = re.search(r"\nFROM\b", select_body, re.IGNORECASE)
    if from_match:
        select_body = select_body[: from_match.start()]

    select_body = re.sub(
        r"CASE\b.*?END",
        lambda m: m.group().replace("\n", " "),
        select_body,
        flags=re.IGNORECASE | re.DOTALL,
    )

    columns = []
    for line in select_body.split("\n"):
        line = re.sub(r"/\*.*?\*/", "", line).strip().rstrip(",")
        if not line:
            continue
        as_match = re.search(r"\bAS\s+(\w+)\s*$", line, re.IGNORECASE)
        if as_match:
            columns.append(as_match.group(1).lower())
            continue
        if not re.search(r"\bAS\b", line, re.IGNORECASE):
            if re.search(r"::\w+", line) or line.endswith("(") or line.startswith(")"):
                continue
            if re.match(r"^\s*[\w.]+\s*,?\s*$", line):
                ident_match = re.search(r"(\w+)\s*$", line)
                if ident_match:
                    columns.append(ident_match.group(1).lower())

    return columns


def read_model_sql(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_columns(
    columns: list[str],
    substitutions: dict[str, str] | None = None,
    exclude: set[str] | None = None,
) -> list[str]:
    substitutions = substitutions or {}
    exclude = exclude or set()
    normalized = []
    for col in columns:
        if col in exclude:
            continue
        normalized.append(substitutions.get(col, col))
    return normalized


def check_column_list_parity(
    reference_cols: list[str],
    other_cols: list[str],
    reference_name: str,
    other_name: str,
) -> list[str]:
    if reference_cols == other_cols:
        return []

    ref_set = set(reference_cols)
    other_set = set(other_cols)
    missing = ref_set - other_set
    extra = other_set - ref_set
    detail = []
    if missing:
        detail.append(f"  missing columns: {sorted(missing)}")
    if extra:
        detail.append(f"  extra columns: {sorted(extra)}")
    if not missing and not extra:
        detail.append("  column order differs")
        detail.append(f"    {reference_name}: {reference_cols}")
        detail.append(f"    {other_name}: {other_cols}")
    return [f"{other_name} does not match {reference_name}:\n" + "\n".join(detail)]


def check_dimension_set_parity(
    left_cols: set[str],
    right_cols: set[str],
    left_name: str,
    right_name: str,
) -> list[str]:
    errors = []
    in_left_not_right = left_cols - right_cols
    in_right_not_left = right_cols - left_cols
    if in_left_not_right:
        errors.append(
            f"Dimension columns in {left_name} but missing from {right_name}: "
            f"{sorted(in_left_not_right)}"
        )
    if in_right_not_left:
        errors.append(
            f"Dimension columns in {right_name} but missing from {left_name}: "
            f"{sorted(in_right_not_left)}"
        )
    return errors
