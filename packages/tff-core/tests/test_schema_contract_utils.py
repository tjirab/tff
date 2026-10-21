"""Tests for schema contract utilities."""

from __future__ import annotations

import pytest
import sqlglot

from tff.core.utils.schema_contract_utils import (
    check_column_list_parity,
    extract_final_select_columns,
    normalize_columns,
)


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        (
            "SELECT\n  id AS account_id,\n  name\nFROM t",
            ["account_id", "name"],
        ),
        (
            "SELECT id, user_name AS name FROM users",
            ["id", "name"],
        ),
        (
            """
            WITH base AS (
                SELECT raw_id, org_id, created_at, state_code FROM raw_events
            )
            SELECT
                raw_id AS event_id,
                CASE
                    WHEN state_code = 1 THEN 'active'
                    ELSE 'inactive'
                END AS status,
                ROW_NUMBER() OVER (
                    PARTITION BY org_id
                    ORDER BY created_at DESC
                ) AS rn
            FROM base
            """,
            ["event_id", "status", "rn"],
        ),
        (
            "SELECT * FROM users",
            [],
        ),
        (
            "SELECT t.*, id, {{ some_macro() }} FROM users t",
            ["id"],
        ),
        (
            "SELECT\n"
            "  {% for col in cols %}\n"
            "  {{ col }} AS {{ col }}_alias,\n"
            "  {% endfor %}\n"
            "  id AS user_id,\n"
            "  t.name\n"
            "FROM (\n",
            ["user_id", "name"],
        ),
        (
            "CREATE TABLE users (id INT)",
            [],
        ),
    ],
)
def test_extract_final_select_columns(sql: str, expected: list[str]) -> None:
    assert extract_final_select_columns(sql) == expected


def test_extract_final_select_columns_with_preparsed_ast() -> None:
    ast = sqlglot.parse_one("SELECT id, email AS user_email FROM users")
    assert extract_final_select_columns("", ast=ast) == ["id", "user_email"]


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
