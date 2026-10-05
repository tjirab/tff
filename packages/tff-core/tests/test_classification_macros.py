from pathlib import Path
from unittest.mock import patch
import pytest

from conftest import _make_model
from tff.core.config import FitnessFunctionsConfig
from tff.core.rules.classification_macros import ClassificationMacros, find_classification_violations


@pytest.mark.parametrize(
    ("sql", "columns", "expected_count"),
    [
        (
            "SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END AS product_type FROM t",
            {"product_type": r"@product_type\b"},
            1,
        ),
        (
            "SELECT @product_type(col := x) AS product_type FROM t",
            {"product_type": r"@product_type\b"},
            0,
        ),
    ],
)
def test_find_classification_violations(sql: str, columns: dict[str, str], expected_count: int) -> None:
    violations = find_classification_violations(sql, columns)
    assert len(violations) == expected_count
    if expected_count > 0:
        assert "product_type" in violations[0]


def _make_rule() -> ClassificationMacros:
    config = FitnessFunctionsConfig()
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.columns = {"product_type": r"@product_type\b"}
    return ClassificationMacros(config=config)


def test_classification_macros_rule_missing_file_and_directory(tmp_path: Path) -> None:
    rule = _make_rule()

    # Missing file path
    assert rule.check_model(_make_model(path="models/core/missing.sql", query=None, dialect="bigquery")) is None

    # Directory path without query
    assert rule.check_model(_make_model(path=str(tmp_path), query=None)) is None

    # Directory path with query containing violation
    violation = rule.check_model(
        _make_model(
            path=str(tmp_path),
            query="SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END AS product_type FROM t",
        )
    )
    assert violation is not None
    assert "product_type" in violation.violation_msg[0]


def test_classification_macros_rule_read_errors_and_disk_file(tmp_path: Path) -> None:
    rule = _make_rule()

    sql_file = tmp_path / "my_model.sql"
    sql_file.write_text("SELECT CASE WHEN x = 1 THEN 'a' ELSE 'b' END AS product_type FROM t", encoding="utf-8")
    model = _make_model(path=str(sql_file), query=None, dialect="bigquery")

    # Read error gracefully returns None
    with patch.object(Path, "read_text", side_effect=OSError("Disk error")):
        assert rule.check_model(model) is None

    # Normal disk read finds violation
    violation = rule.check_model(model)
    assert violation is not None
    assert "product_type" in violation.violation_msg[0]

    # Compliant SQL on disk returns None
    sql_file.write_text("SELECT @product_type(col := x) AS product_type FROM t", encoding="utf-8")
    assert rule.check_model(model) is None
