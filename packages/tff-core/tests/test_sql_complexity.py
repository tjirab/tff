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


def test_format_violations_fail_threshold() -> None:
    metrics = {"line_count": 500, "decision_points": 0, "cte_count": 0, "join_count": 0}
    thresholds = {"line_count": [250, 400]}
    messages = format_violations(metrics, "schema.model", thresholds)
    assert messages
    assert "FAIL" in messages[0]


def test_format_violations_nested_subquery() -> None:
    metrics = {
        "line_count": 10,
        "decision_points": 0,
        "cte_count": 0,
        "join_count": 0,
        "nested_subquery_in_final_select": True,
    }
    thresholds = {"line_count": [250, 400]}
    messages = format_violations(metrics, "schema.model", thresholds)
    assert any("WARN: nested subquery" in m for m in messages)


def test_sql_complexity_rejects_warn_only() -> None:
    import pytest
    from pydantic import ValidationError
    from tff.core.config import FitnessFunctionsConfig, SqlComplexityRuleConfig

    # Direct validation with warn_only
    with pytest.raises(
        ValidationError, match="warn_only.*deprecated and no longer supported"
    ):
        SqlComplexityRuleConfig.model_validate({"warn_only": True})

    with pytest.raises(
        ValidationError, match="warn_only.*deprecated and no longer supported"
    ):
        SqlComplexityRuleConfig.model_validate({"warn_only": False})

    # Setting attribute after creation
    cfg = SqlComplexityRuleConfig()
    with pytest.raises(
        ValueError, match="warn_only.*deprecated and no longer supported"
    ):
        cfg.warn_only = False

    with pytest.raises(
        AttributeError, match="warn_only.*deprecated and no longer supported"
    ):
        _ = cfg.warn_only

    # In FitnessFunctionsConfig via dict
    with pytest.raises(
        ValidationError, match="warn_only.*deprecated and no longer supported"
    ):
        FitnessFunctionsConfig.model_validate(
            {
                "rules": {
                    "sql_complexity": {
                        "enabled": True,
                        "warn_only": True,
                    }
                }
            }
        )


def test_sql_complexity_parallel_model_rule_severities() -> None:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.parallel import run_parallel_model_rule
    from tff.core.rules.sql_complexity import SqlComplexity

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True

    # SQL with 9 CTEs (warn>8, fail>12) and 26 decision points (warn>15, fail>25)
    ctes = ", ".join(f"cte_{i} AS (SELECT {i})" for i in range(9))
    cases = " ".join(f"CASE WHEN id = {i} THEN {i} ELSE 0 END +" for i in range(26))
    sql = f"WITH {ctes} SELECT {cases} 0 FROM cte_0"

    model = ModelRepresentation(
        name="core.complex_model",
        path="models/core/complex_model.sql",
        dialect="duckdb",
        query=sql,
    )

    # Sequential execution
    findings_seq = run_parallel_model_rule(
        SqlComplexity,
        [model],
        config=config,
        max_workers=1,
    )
    # Findings should be split into individual items
    warn_findings = [f for f in findings_seq if f.severity == "warning"]
    fail_findings = [f for f in findings_seq if f.severity == "error"]

    assert len(warn_findings) >= 1
    assert any("WARN: cte_count=9" in f.message for f in warn_findings)
    assert len(fail_findings) >= 1
    assert any("FAIL: decision_points=" in f.message for f in fail_findings)

    # When rule severity is overridden to warning
    findings_override = run_parallel_model_rule(
        SqlComplexity,
        [model],
        severity="warning",
        config=config,
        max_workers=1,
    )
    assert all(f.severity == "warning" for f in findings_override)

    # Multithreaded execution
    models = [
        ModelRepresentation(
            name=f"core.complex_model_{i}",
            path=f"models/core/complex_model_{i}.sql",
            dialect="duckdb",
            query=sql,
        )
        for i in range(25)
    ]
    findings_mt = run_parallel_model_rule(
        SqlComplexity,
        models,
        config=config,
        max_workers=4,
    )
    assert any(f.severity == "warning" for f in findings_mt)
    assert any(f.severity == "error" for f in findings_mt)


def test_sql_complexity_rule_missing_or_non_sql_file() -> None:
    from tff.core.rules.sql_complexity import SqlComplexity
    from tff.core.model import ModelRepresentation
    from tff.core.config import FitnessFunctionsConfig

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True

    rule = SqlComplexity(config=config)

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
    from tff.core.rules.sql_complexity import SqlComplexity
    from tff.core.model import ModelRepresentation
    from tff.core.config import FitnessFunctionsConfig

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True

    rule = SqlComplexity(config=config)

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


def test_has_nested_subquery_in_final_select() -> None:
    import sqlglot
    from tff.core.rules.sql_complexity import has_nested_subquery_in_final_select

    # Subquery in FROM
    q1 = sqlglot.parse_one("SELECT * FROM (SELECT 1) sub")
    assert has_nested_subquery_in_final_select(q1) is True

    # Subquery in JOIN
    q2 = sqlglot.parse_one("SELECT * FROM t JOIN (SELECT 1) sub ON true")
    assert has_nested_subquery_in_final_select(q2) is True

    # Subquery inside CTE, but final SELECT has no subqueries in FROM/JOIN
    q3 = sqlglot.parse_one("WITH cte AS (SELECT * FROM (SELECT 1) s) SELECT * FROM cte")
    assert has_nested_subquery_in_final_select(q3) is False

    # Subquery in WHERE clause
    q4 = sqlglot.parse_one("SELECT * FROM t WHERE id IN (SELECT id FROM other)")
    assert has_nested_subquery_in_final_select(q4) is False

    # Subquery in SELECT expressions
    q5 = sqlglot.parse_one("SELECT (SELECT 1) AS x FROM t")
    assert has_nested_subquery_in_final_select(q5) is False

