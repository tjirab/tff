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
    assert "missing columns: b" in errors[0]


def test_column_list_parity_detects_extra() -> None:
    errors = check_column_list_parity(
        ["a"],
        ["a", "b"],
        "ref.sql",
        "other.sql",
    )
    assert len(errors) == 1
    assert "extra columns: b" in errors[0]


def test_column_list_parity_detects_order_differs() -> None:
    errors = check_column_list_parity(
        ["a", "b"],
        ["b", "a"],
        "ref.sql",
        "other.sql",
    )
    assert len(errors) == 1
    assert "column order differs" in errors[0]
    assert "ref.sql: a, b" in errors[0]
    assert "other.sql: b, a" in errors[0]


def test_dimension_set_parity() -> None:
    from tff.core.utils.schema_contract_utils import check_dimension_set_parity

    errors = check_dimension_set_parity(
        {"a", "b"},
        {"b", "c"},
        "left.sql",
        "right.sql",
    )
    assert len(errors) == 2
    assert "Dimension columns in left.sql but missing from right.sql: a" in errors[0]
    assert "Dimension columns in right.sql but missing from left.sql: c" in errors[1]


def test_normalize_columns_substitutions() -> None:
    assert normalize_columns(["month"], {"month": "<time>"}) == ["<time>"]
