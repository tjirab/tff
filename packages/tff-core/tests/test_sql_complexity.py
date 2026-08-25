"""Tests for SQL complexity analysis."""

from pathlib import Path
from tff.core.rules.sql_complexity import analyze_sql, format_violations


def test_analyze_sql_counts_ctes() -> None:
    sql = """
    WITH a AS (SELECT 1), b AS (SELECT 2)
    SELECT * FROM a JOIN b ON true
    """
    metrics = analyze_sql(sql, "bigquery")
    assert metrics["cte_count"] == 2
    assert metrics["join_count"] >= 1


def test_format_violations_warn_threshold() -> None:
    metrics = {"line_count": 300, "decision_points": 0, "cte_count": 0, "join_count": 0}
    thresholds = {"line_count": [250, 400]}
    messages = format_violations(metrics, "schema.model", thresholds)
    assert messages
    assert "WARN" in messages[0]


def test_sql_complexity_rule_missing_or_non_sql_file() -> None:
    from tff.core.rules.sql_complexity import SqlComplexity
    from tff.core.model import ModelRepresentation
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.context import set_ff_config

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True
    set_ff_config(config)

    rule = SqlComplexity()

    # Case 1: non-existent file
    model1 = ModelRepresentation(
        name="core.model1",
        path="models/core/non_existent_file.sql",
        dialect="bigquery",
        query=None,
    )
    assert rule.check_model(model1) is None

    # Case 2: non-sql file extension (e.g. .txt)
    model2 = ModelRepresentation(
        name="core.model2",
        path="models/core/file.txt",
        dialect="bigquery",
        query=None,
    )
    assert rule.check_model(model2) is None


def test_analyze_sql_empty_string() -> None:
    metrics = analyze_sql("", "duckdb")
    assert metrics["line_count"] == 0
    assert metrics["cte_count"] == 0


def test_analyze_sql_invalid_sql() -> None:
    metrics = analyze_sql("SELECT FROM WHERE;", "duckdb")
    assert metrics["line_count"] == 1
    assert metrics["cte_count"] == 0


def test_sql_complexity_rule_read_exception(tmp_path: Path) -> None:
    from pathlib import Path
    from tff.core.rules.sql_complexity import SqlComplexity
    from tff.core.model import ModelRepresentation
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.context import set_ff_config

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True
    set_ff_config(config)

    rule = SqlComplexity()

    # Create a directory ending with .sql to raise IsADirectoryError upon read
    invalid_dir = tmp_path / "invalid_model.sql"
    invalid_dir.mkdir()

    model = ModelRepresentation(
        name="core.invalid_model",
        path=str(invalid_dir),
        dialect="bigquery",
        query=None,
    )
    assert rule.check_model(model) is None

