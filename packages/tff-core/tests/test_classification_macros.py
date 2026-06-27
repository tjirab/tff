"""Tests for classification macro detection."""

from tff.core.rules.classification_macros import find_classification_violations


def test_inline_case_without_macro_is_violation() -> None:
    sql = """
    SELECT
      CASE WHEN x = 1 THEN 'a' ELSE 'b' END AS product_type
    FROM t
    """
    columns = {"product_type": r"@product_type\b"}
    violations = find_classification_violations(sql, columns)
    assert len(violations) == 1
    assert "product_type" in violations[0]


def test_macro_usage_is_allowed() -> None:
    sql = "SELECT @product_type(col := x) AS product_type FROM t"
    columns = {"product_type": r"@product_type\b"}
    violations = find_classification_violations(sql, columns)
    assert violations == []
