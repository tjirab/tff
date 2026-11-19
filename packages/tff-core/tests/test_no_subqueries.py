from pathlib import Path
import pytest

from conftest import _make_model
from tff.core.config import FitnessFunctionsConfig
from tff.core.rules.no_subqueries import NoSubqueries, find_subqueries


@pytest.mark.parametrize(
    ("path", "query", "is_symbolic", "expect_violation"),
    [
        # Violations: Various subquery locations
        ("models/marts/sub_from.sql", "SELECT * FROM (SELECT id FROM users)", False, True),
        ("models/marts/sub_join.sql", "SELECT * FROM users u JOIN (SELECT id FROM orders) o ON u.id = o.id", False, True),
        ("models/marts/sub_select.sql", "SELECT id, (SELECT MAX(amount) FROM orders) AS max_amt FROM users", False, True),
        ("models/marts/sub_in.sql", "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)", False, True),
        ("models/marts/sub_comp.sql", "SELECT * FROM users WHERE id = (SELECT MAX(id) FROM users)", False, True),
        ("models/marts/sub_exists.sql", "SELECT * FROM users WHERE EXISTS (SELECT 1 FROM orders WHERE user_id = users.id)", False, True),
        ("models/marts/sub_having.sql", "SELECT id, COUNT(*) FROM t GROUP BY id HAVING COUNT(*) > (SELECT AVG(c) FROM u)", False, True),
        ("models/marts/sub_in_cte.sql", "WITH a AS (SELECT * FROM (SELECT 1 AS id)) SELECT * FROM a", False, True),
        # Compliant models
        ("models/marts/compliant_simple.sql", "SELECT id, name FROM users", False, False),
        ("models/marts/compliant_cte.sql", "WITH a AS (SELECT 1 AS id), b AS (SELECT 2 AS id) SELECT a.id, b.id FROM a JOIN b ON a.id = b.id", False, False),
        ("models/marts/compliant_paren_cte.sql", "WITH a AS ((SELECT 1 AS id)) SELECT * FROM a", False, False),
        ("models/marts/compliant_union.sql", "SELECT 1 AS id UNION ALL SELECT 2 AS id", False, False),
        ("models/marts/compliant_paren_union.sql", "(SELECT 1 AS id) UNION ALL (SELECT 2 AS id)", False, False),
        ("models/marts/compliant_triple_union.sql", "(SELECT 1 AS id) UNION ALL (SELECT 2 AS id) UNION ALL (SELECT 3 AS id)", False, False),
        ("models/marts/compliant_cte_union.sql", "WITH a AS (SELECT 1 AS id UNION ALL SELECT 2 AS id) SELECT * FROM a", False, False),
        ("models/marts/compliant_cte_paren_union.sql", "WITH a AS ((SELECT 1 AS id) UNION ALL (SELECT 2 AS id)) SELECT * FROM a", False, False),
        ("models/marts/compliant_intersect.sql", "(SELECT 1 AS id) INTERSECT (SELECT 2 AS id)", False, False),
        ("models/marts/compliant_except.sql", "(SELECT 1 AS id) EXCEPT (SELECT 2 AS id)", False, False),
        # Exemptions
        ("models/sources/sub_in_source.sql", "SELECT * FROM (SELECT id FROM users)", False, False),
        ("models/marts/symbolic_model.sql", "SELECT * FROM (SELECT id FROM users)", True, False),
    ],
)
def test_no_subqueries_rule(path: str, query: str, is_symbolic: bool, expect_violation: bool) -> None:
    config = FitnessFunctionsConfig()
    config.rules.no_subqueries.enabled = True
    config.rules.no_subqueries.skip_layers = ["sources"]
    rule = NoSubqueries(config=config)

    model = _make_model(name=Path(path).stem, path=path, query=query, is_symbolic=is_symbolic, dialect="duckdb")
    violation = rule.check_model(model)
    if expect_violation:
        assert violation is not None
        assert "Subqueries are prohibited" in violation.violation_msg[0]
    else:
        assert violation is None


def test_no_subqueries_disk_read(tmp_path: Path) -> None:
    config = FitnessFunctionsConfig()
    config.rules.no_subqueries.enabled = True
    rule = NoSubqueries(config=config)

    sql_file = tmp_path / "models" / "marts" / "model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM (SELECT 1 AS id)", encoding="utf-8")
    model = _make_model(name="marts.disk_model", path=str(sql_file), query=None, dialect="duckdb")
    violation = rule.check_model(model)
    assert violation is not None
    assert "1 inline subquery found" in violation.violation_msg[0]


@pytest.mark.parametrize(
    "model_kwargs",
    [
        {"path": "non_existent_file.sql", "query": None},
        {"query": "SELECT * FROM (invalid syntax"},
    ],
)
def test_no_subqueries_error_paths(model_kwargs: dict) -> None:
    config = FitnessFunctionsConfig()
    config.rules.no_subqueries.enabled = True
    rule = NoSubqueries(config=config)

    model = _make_model(name="marts.err_model", dialect="duckdb", **model_kwargs)
    assert rule.check_model(model) is None


def test_no_subqueries_multiple_subqueries() -> None:
    config = FitnessFunctionsConfig()
    config.rules.no_subqueries.enabled = True
    rule = NoSubqueries(config=config)

    query = "SELECT (SELECT 1), * FROM (SELECT 2)"
    model = _make_model(name="marts.multi_sub", path="models/marts/multi_sub.sql", query=query, dialect="duckdb")
    violation = rule.check_model(model)
    assert violation is not None
    assert isinstance(violation.violation_msg, list)
    assert len(violation.violation_msg) == 1
    assert "2 inline subqueries found" in violation.violation_msg[0]


def test_no_subqueries_disabled() -> None:
    config = FitnessFunctionsConfig()
    config.rules.no_subqueries.enabled = False
    rule = NoSubqueries(config=config)

    query = "SELECT * FROM (SELECT 1)"
    model = _make_model(name="marts.disabled_model", path="models/marts/disabled_model.sql", query=query, dialect="duckdb")
    assert rule.check_model(model) is None


def test_no_subqueries_layer_filtering() -> None:
    config = FitnessFunctionsConfig()
    config.rules.no_subqueries.enabled = True
    config.rules.no_subqueries.only_layers = ["marts"]
    rule = NoSubqueries(config=config)

    query = "SELECT * FROM (SELECT 1)"
    m_core = _make_model(name="core.m", path="models/core/m.sql", query=query, dialect="duckdb")
    m_mart = _make_model(name="marts.m", path="models/marts/m.sql", query=query, dialect="duckdb")

    assert rule.check_model(m_core) is None
    assert rule.check_model(m_mart) is not None


def test_find_subqueries_helper() -> None:
    import sqlglot

    # Top-level query without parent is not flagged as an inner subquery
    ast = sqlglot.parse_one("(SELECT 1)")
    assert find_subqueries(ast) == []

    # Explicit subquery is extracted
    ast_with_sub = sqlglot.parse_one("SELECT * FROM (SELECT 1 AS id)")
    subqueries = find_subqueries(ast_with_sub)
    assert len(subqueries) == 1
