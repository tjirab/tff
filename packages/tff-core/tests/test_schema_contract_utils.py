"""Tests for schema contract utilities."""

from tff.core.utils.schema_contract_utils import (
    check_column_list_parity,
    extract_final_select_columns,
    normalize_columns,
)


def test_extract_final_select_columns() -> None:
    sql = """
SELECT
  id AS account_id,
  name
FROM t
"""
    cols = extract_final_select_columns(sql)
    assert cols == ["account_id", "name"]


def test_column_list_parity_detects_missing() -> None:
    errors = check_column_list_parity(
        ["a", "b"],
        ["a"],
        "ref.sql",
        "other.sql",
    )
    assert len(errors) == 1
    assert "missing columns" in errors[0]


def test_normalize_columns_substitutions() -> None:
    assert normalize_columns(["month"], {"month": "<time>"}) == ["<time>"]
