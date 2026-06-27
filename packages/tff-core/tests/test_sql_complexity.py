"""Tests for SQL complexity analysis."""

from tff.core.rules.sql_complexity import analyze_sql, format_violations


def test_analyze_sql_counts_ctes() -> None:
    sql = """
    WITH a AS (SELECT 1), b AS (SELECT 2)
    SELECT * FROM a JOIN b ON true
    """
    metrics = analyze_sql(sql)
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
        query=None,
    )
    assert rule.check_model(model1) is None

    # Case 2: non-sql file extension (e.g. .txt)
    model2 = ModelRepresentation(
        name="core.model2",
        path="models/core/file.txt",
        query=None,
    )
    assert rule.check_model(model2) is None
