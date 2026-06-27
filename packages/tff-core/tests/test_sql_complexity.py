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
