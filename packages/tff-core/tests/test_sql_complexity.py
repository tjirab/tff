"""Tests for SQL complexity analysis."""

from pathlib import Path
from typing import Any

import pytest

from conftest import _make_model
from tff.core.rules.sql_complexity import (
    analyze_sql,
    format_violations,
    parse_complexity_findings,
    split_complexity_message,
)


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


@pytest.mark.parametrize(
    "msg,base_severity,expected",
    [
        (
            "WARN: cte_count=9 (warn>8, fail>12)",
            "error",
            [("WARN: cte_count=9 (warn>8, fail>12)", "warning")],
        ),
        (
            "FAIL: cte_count=13 (warn>8, fail>12)",
            "error",
            [("FAIL: cte_count=13 (warn>8, fail>12)", "error")],
        ),
        (
            "WARN: cte_count=9 (warn>8, fail>12); "
            "FAIL: join_count=15 (warn>10, fail>14); "
            "WARN: nested subquery in final SELECT — prefer CTEs per style guide",
            "error",
            [
                ("WARN: cte_count=9 (warn>8, fail>12)", "warning"),
                ("FAIL: join_count=15 (warn>10, fail>14)", "error"),
                ("WARN: nested subquery in final SELECT — prefer CTEs per style guide", "warning"),
            ],
        ),
        (
            "WARN: cte_count=9 (warn>8, fail>12); FAIL: join_count=15 (warn>10, fail>14)",
            "warning",
            [
                ("WARN: cte_count=9 (warn>8, fail>12)", "warning"),
                ("FAIL: join_count=15 (warn>10, fail>14)", "warning"),
            ],
        ),
    ],
)
def test_split_complexity_message_variants(
    msg: str, base_severity: str, expected: list[tuple[str, str]]
) -> None:
    res = split_complexity_message(msg, base_severity=base_severity)  # type: ignore[arg-type]
    assert res == expected


def test_split_complexity_message_with_model_prefix() -> None:
    msg = "core.my_model: WARN: cte_count=9 (warn>8, fail>12); FAIL: join_count=15 (warn>10, fail>14)"
    # With explicit model_name
    res_explicit = split_complexity_message(msg, model_name="core.my_model")
    assert res_explicit == [
        ("WARN: cte_count=9 (warn>8, fail>12)", "warning"),
        ("FAIL: join_count=15 (warn>10, fail>14)", "error"),
    ]
    # Without explicit model_name (inferred prefix strip)
    res_inferred = split_complexity_message(msg)
    assert res_inferred == [
        ("WARN: cte_count=9 (warn>8, fail>12)", "warning"),
        ("FAIL: join_count=15 (warn>10, fail>14)", "error"),
    ]


def test_split_complexity_message_empty_or_whitespace() -> None:
    assert split_complexity_message("") == []
    assert split_complexity_message("   ;  ;  ") == []


def test_split_complexity_message_unprefixed_part() -> None:
    res_err = split_complexity_message("custom violation message", base_severity="error")
    assert res_err == [("custom violation message", "error")]

    res_warn = split_complexity_message("custom violation message", base_severity="warning")
    assert res_warn == [("custom violation message", "warning")]


def test_parse_complexity_findings_alias() -> None:
    assert parse_complexity_findings is split_complexity_message


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
    from tff.core.parallel import run_parallel_model_rule
    from tff.core.rules.sql_complexity import SqlComplexity

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True

    # SQL with 9 CTEs (warn>8, fail>12) and 26 decision points (warn>15, fail>25)
    ctes = ", ".join(f"cte_{i} AS (SELECT {i})" for i in range(9))
    cases = " ".join(f"CASE WHEN id = {i} THEN {i} ELSE 0 END +" for i in range(26))
    sql = f"WITH {ctes} SELECT {cases} 0 FROM cte_0"

    model = _make_model(
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
        _make_model(
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
    from tff.core.config import FitnessFunctionsConfig

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True

    rule = SqlComplexity(config=config)

    # Case 1: non-existent file
    model1 = _make_model(
        name="core.model1",
        path="models/core/non_existent_file.sql",
        dialect="bigquery",
        query=None,
    )
    assert rule.check_model(model1) is None

    # Case 2: non-sql file extension (e.g. .txt)
    model2 = _make_model(
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
    from tff.core.config import FitnessFunctionsConfig

    config = FitnessFunctionsConfig()
    config.rules.sql_complexity.enabled = True

    rule = SqlComplexity(config=config)

    # Create a directory ending with .sql to raise IsADirectoryError upon read
    invalid_dir = tmp_path / "invalid_model.sql"
    invalid_dir.mkdir()

    model = _make_model(
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


def test_inspect_sql_complexity_detailed_breakdown() -> None:
    from tff.core.rules.sql_complexity import inspect_sql_complexity

    sql = """WITH active_users AS (
    SELECT
        id,
        CASE
            WHEN status = 'active' THEN 1
            WHEN status = 'trial' THEN 2
            ELSE 0
        END AS status_code
    FROM raw.users
    WHERE age >= 18
      AND country = 'NL'
),
vip_users AS (
    SELECT
        u.id,
        u.status_code
    FROM active_users u
    LEFT JOIN raw.purchases p ON u.id = p.user_id
    WHERE p.amount > 1000
       OR p.is_vip = 1
)
SELECT * FROM vip_users
"""
    inspection = inspect_sql_complexity(
        sql,
        dialect="duckdb",
        model_name="analytics.vip_users",
        path="models/analytics/vip_users.sql",
    )

    assert inspection.model_name == "analytics.vip_users"
    assert inspection.path == "models/analytics/vip_users.sql"
    assert inspection.dialect == "duckdb"
    assert inspection.metrics["cte_count"] == 2
    assert inspection.metrics["join_count"] == 1
    assert inspection.metrics["decision_points"] == 5
    assert len(inspection.decision_points) == 5

    # Check decision points kinds and line coordinates
    kinds = [dp.kind for dp in inspection.decision_points]
    assert kinds == ["case", "when", "when", "where_and", "where_or"]

    # Verify CTE scoping
    ctes = [dp.cte_name for dp in inspection.decision_points]
    assert ctes[:4] == ["active_users", "active_users", "active_users", "active_users"]
    assert ctes[4] == "vip_users"

    # Verify line numbers are captured
    lines = [dp.line for dp in inspection.decision_points]
    assert all(line is not None and line > 0 for line in lines)
    assert lines == sorted(lines)

    # Verify CTE details
    assert len(inspection.ctes) == 2
    assert inspection.ctes[0].name == "active_users"
    assert inspection.ctes[1].name == "vip_users"

    # Verify Join details
    assert len(inspection.joins) == 1
    assert "LEFT" in inspection.joins[0].kind
    assert "purchases" in inspection.joins[0].table


def test_inspect_sql_complexity_model_block_preservation() -> None:
    from tff.core.rules.sql_complexity import inspect_sql_complexity

    sql = """MODEL (
  name analytics.customers,
  kind full
);

SELECT
    id,
    CASE
        WHEN status = 'active' THEN 1
        ELSE 0
    END as is_active
FROM raw.users
WHERE age > 18
  AND country = 'NL'
"""
    inspection = inspect_sql_complexity(sql, dialect="duckdb", model_name="analytics.customers")
    assert inspection.metrics["decision_points"] == 3

    # Lines should account for the MODEL header (approx lines 9-16)
    dp_lines = [dp.line for dp in inspection.decision_points if dp.line is not None]
    assert all(ln >= 8 for ln in dp_lines)


def test_inspect_sql_complexity_to_dict_serialization() -> None:
    import json
    from tff.core.rules.sql_complexity import inspect_sql_complexity

    sql = "SELECT id, CASE WHEN x = 1 THEN 'a' END FROM t WHERE y = 2 AND z = 3"
    inspection = inspect_sql_complexity(sql, dialect="duckdb", model_name="test_model")
    d = inspection.to_dict()

    assert d["model_name"] == "test_model"
    assert "metrics" in d
    assert "decision_points" in d
    assert "recommendations" in d
    # Ensure it's valid JSON
    serialized = json.dumps(d)
    assert "decision_points" in serialized


@pytest.mark.parametrize(
    ("metrics", "thresholds", "expected_rec_substr"),
    [
        (
            {"decision_points": 28, "cte_count": 2, "join_count": 2, "line_count": 50},
            {"decision_points": [15, 25], "cte_count": [8, 12], "join_count": [8, 12], "line_count": [250, 400]},
            "decision branch",
        ),
        (
            {"decision_points": 5, "cte_count": 14, "join_count": 2, "line_count": 50},
            {"decision_points": [15, 25], "cte_count": [8, 12], "join_count": [8, 12], "line_count": [250, 400]},
            "defines 14 CTEs",
        ),
        (
            {"decision_points": 5, "cte_count": 2, "join_count": 15, "line_count": 50},
            {"decision_points": [15, 25], "cte_count": [8, 12], "join_count": [8, 12], "line_count": [250, 400]},
            "executes 15 JOINs",
        ),
        (
            {"decision_points": 5, "cte_count": 2, "join_count": 2, "line_count": 450},
            {"decision_points": [15, 25], "cte_count": [8, 12], "join_count": [8, 12], "line_count": [250, 400]},
            "spans 450 lines",
        ),
        (
            {"decision_points": 2, "cte_count": 2, "join_count": 2, "line_count": 50, "nested_subquery_in_final_select": True},
            {"decision_points": [15, 25], "cte_count": [8, 12], "join_count": [8, 12], "line_count": [250, 400]},
            "Final SELECT contains nested subqueries",
        ),
        (
            {"decision_points": 2, "cte_count": 2, "join_count": 2, "line_count": 50},
            {"decision_points": [15, 25], "cte_count": [8, 12], "join_count": [8, 12], "line_count": [250, 400]},
            "within all maintainability thresholds",
        ),
    ],
)
def test_inspect_sql_complexity_recommendations_matrix(
    metrics: dict[str, Any],
    thresholds: dict[str, list[int]],
    expected_rec_substr: str,
) -> None:
    from tff.core.rules.sql_complexity import inspect_sql_complexity

    # Use inspect_sql_complexity with minimal sql to test recommendation engine
    sql = "SELECT 1"
    if metrics.get("nested_subquery_in_final_select"):
        sql = "SELECT * FROM (SELECT 1) s"
    elif metrics.get("decision_points", 0) > 15:
        sql = "SELECT " + " + ".join(f"CASE WHEN id = {i} THEN {i} END" for i in range(20))
    elif metrics.get("cte_count", 0) > 8:
        sql = "WITH " + ", ".join(f"c{i} AS (SELECT {i})" for i in range(14)) + " SELECT * FROM c0"
    elif metrics.get("join_count", 0) > 8:
        sql = "SELECT * FROM t " + " ".join(f"JOIN j{i} ON true" for i in range(15))
    elif metrics.get("line_count", 0) > 250:
        sql = "\n".join(f"SELECT {i};" for i in range(450))

    insp = inspect_sql_complexity(sql, thresholds=thresholds)
    assert any(expected_rec_substr in r for r in insp.recommendations)


def test_inspect_sql_complexity_empty_and_invalid_sql() -> None:
    from tff.core.rules.sql_complexity import inspect_sql_complexity

    insp_empty = inspect_sql_complexity("")
    assert insp_empty.metrics["line_count"] == 0
    assert insp_empty.decision_points == []

    insp_invalid = inspect_sql_complexity("SELECT FROM WHERE ;;;")
    assert insp_invalid.metrics["line_count"] == 1
    assert insp_invalid.decision_points == []


def test_complexity_detail_dataclasses_to_dict() -> None:
    from tff.core.rules.sql_complexity import CteDetail, JoinDetail

    cte = CteDetail(name="stg_orders", line=5)
    assert cte.to_dict() == {"name": "stg_orders", "line": 5}

    join = JoinDetail(kind="LEFT JOIN", table="users", line=12)
    assert join.to_dict() == {"kind": "LEFT JOIN", "table": "users", "line": 12}


def test_inspect_sql_complexity_where_boolean_branches_recommendation() -> None:
    from tff.core.rules.sql_complexity import inspect_sql_complexity

    # Construct SQL with 20 boolean branches in WHERE to trigger WHERE filter recommendation
    where_conditions = " AND ".join(f"col_{i} = {i}" for i in range(20))
    sql = f"SELECT * FROM tbl INNER JOIN other ON true WHERE {where_conditions}"

    insp = inspect_sql_complexity(sql, thresholds={"decision_points": [15, 25]})
    assert insp.metrics["decision_points"] >= 19
    assert insp.thresholds["cte_count"] == [8, 12]
    assert any("boolean filter condition" in r for r in insp.recommendations)
    assert any(j.kind == "INNER" for j in insp.joins)


def test_extract_node_line_col_direct_and_none() -> None:
    import sqlglot.expressions as exp
    from tff.core.rules.sql_complexity import _extract_node_line_col

    # Direct meta on node
    node_with_meta = exp.Literal.number(1)
    node_with_meta.meta["line"] = 10
    node_with_meta.meta["col"] = 4
    line, col = _extract_node_line_col(node_with_meta)
    assert line == 10
    assert col == 4

    # Node with no meta anywhere in tree
    node_empty = exp.Literal.string("val")
    node_empty.meta.clear()
    line_none, col_none = _extract_node_line_col(node_empty)
    assert line_none is None
    assert col_none is None



