from pathlib import Path
from unittest.mock import patch

from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.rules.classification_macros import ClassificationMacros, find_classification_violations


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
    config = FitnessFunctionsConfig()
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.columns = {"product_type": "macro"}

    # Path does not exist
    model = ModelRepresentation(
        name="core.model",
        path="models/core/non_existent_file.sql",
        dialect="bigquery",
        query=None,
    )
    rule = ClassificationMacros(config=config)
    assert rule.check_model(model) is None


def test_classification_macros_rule_directory_path(tmp_path: Path) -> None:
    """Ensure directory path in model.path does not raise IsADirectoryError."""
    config = FitnessFunctionsConfig()
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.columns = {"product_type": r"@product_type\b"}

    rule = ClassificationMacros(config=config)

    # Directory path without query
    model_dir = ModelRepresentation(
        name="dep_pkg.model",
        path=str(tmp_path),
        dialect="duckdb",
        is_symbolic=False,
        query=None,
    )
    assert rule.check_model(model_dir) is None

    # Directory path with query containing violation
    model_dir_with_query = ModelRepresentation(
        name="dep_pkg.model_violation",
        path=str(tmp_path),
        dialect="duckdb",
        is_symbolic=False,
        query="SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END AS product_type FROM t",
    )
    violation = rule.check_model(model_dir_with_query)
    assert violation is not None
    assert "product_type" in violation.violation_msg[0]


def test_classification_macros_rule_read_text_error(tmp_path: Path) -> None:
    """Ensure read_text exceptions are handled gracefully."""
    config = FitnessFunctionsConfig()
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.columns = {"product_type": r"@product_type\b"}

    rule = ClassificationMacros(config=config)

    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END AS product_type FROM t", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.my_model",
        path=str(sql_file),
        dialect="bigquery",
        is_symbolic=False,
    )

    with patch.object(Path, "read_text", side_effect=OSError("Disk error")):
        assert rule.check_model(model) is None


def test_classification_macros_rule_reads_file(tmp_path: Path) -> None:
    """Ensure valid file is read from disk and inspected."""
    config = FitnessFunctionsConfig()
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.columns = {"product_type": r"@product_type\b"}

    rule = ClassificationMacros(config=config)

    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END AS product_type FROM t", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.my_model",
        path=str(sql_file),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation = rule.check_model(model)
    assert violation is not None
    assert "product_type" in violation.violation_msg[0]

    # Now with macro
    sql_file.write_text("SELECT @product_type(col := x) AS product_type FROM t", encoding="utf-8")
    assert rule.check_model(model) is None

