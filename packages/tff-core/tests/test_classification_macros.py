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


def test_classification_macros_rule_missing_file() -> None:
    from tff.core.rules.classification_macros import ClassificationMacros
    from tff.core.model import ModelRepresentation
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.context import set_ff_config

    config = FitnessFunctionsConfig()
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.columns = {"product_type": "macro"}
    set_ff_config(config)

    # Path does not exist
    model = ModelRepresentation(
        name="core.model",
        path="models/core/non_existent_file.sql",
        dialect="bigquery",
        query=None,
    )
    rule = ClassificationMacros()
    assert rule.check_model(model) is None
