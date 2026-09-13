from pathlib import Path

from tff.core.checks.duplicate_ctes import collect_duplicate_cte_findings
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation


def test_duplicate_ctes_no_duplicates():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="""
        WITH cte1 AS (
            SELECT a, b FROM ref('stg_a') WHERE a > 10 JOIN other ON a = id
        )
        SELECT * FROM cte1
        """,
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="""
        WITH cte2 AS (
            SELECT c, d FROM ref('stg_b') WHERE c < 5 JOIN another ON c = id
        )
        SELECT * FROM cte2
        """,
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_duplicate_cte_findings(models, config)
    assert len(findings) == 0


def test_duplicate_ctes_with_duplicates():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    # Identical query logic inside CTEs in two different models
    query1 = """
    WITH cleaning_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM ref('stg_users')
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT * FROM cleaning_cte
    """

    query2 = """
    WITH user_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM ref('stg_users')
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT id FROM user_cte
    """

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query=query1,
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query=query2,
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_duplicate_cte_findings(models, config)
    assert len(findings) == 2

    # Verify report structure
    finding_models = {f.model for f in findings}
    assert finding_models == {"model1", "model2"}
    assert all(f.check == "duplicate_ctes" for f in findings)
    assert all(f.severity == "warning" for f in findings)
    assert all(f.path is not None and "models/marts" in f.path for f in findings)
    assert "has duplicate transformation logic" in findings[0].message


def test_duplicate_ctes_simple_ignored():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True

    # Simple import CTEs that should be ignored
    query1 = "WITH imported AS (SELECT * FROM ref('stg_users')) SELECT * FROM imported"
    query2 = "WITH import_alias AS (SELECT * FROM ref('stg_users')) SELECT id FROM import_alias"

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query=query1,
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query=query2,
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_duplicate_cte_findings(models, config)
    assert len(findings) == 0


def test_duplicate_ctes_layer_filtering():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.skip_layers = ["sources"]

    query = """
    WITH complex_cte AS (
        SELECT id, val FROM ref('stg_data') WHERE val > 100 JOIN details USING (id)
    )
    SELECT * FROM complex_cte
    """

    model1 = ModelRepresentation(
        name="sources.model1",
        path="models/sources/model1.sql",
        dialect="postgres",
        query=query,
    )
    model2 = ModelRepresentation(
        name="marts.model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query=query,
    )

    models = {"sources.model1": model1, "marts.model2": model2}
    findings = collect_duplicate_cte_findings(models, config)
    # Since model1 is in "sources" and is skipped, its CTE is not analyzed.
    # Therefore, marts.model2's CTE is unique and not flagged.
    assert len(findings) == 0


def test_duplicate_ctes_disabled():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = False

    query = """
    WITH complex_cte AS (
        SELECT id, val FROM ref('stg_data') WHERE val > 100 JOIN details USING (id)
    )
    SELECT * FROM complex_cte
    """

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query=query,
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query=query,
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_duplicate_cte_findings(models, config)
    assert len(findings) == 0


def test_duplicate_ctes_file_fallbacks(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True

    # 1. Nonexistent/invalid path
    model_nonexistent = ModelRepresentation(
        name="model1",
        path="nonexistent.txt",
        dialect="postgres",
        query=None,
    )
    assert collect_duplicate_cte_findings({"m": model_nonexistent}, config) == []

    # 2. Existing path with read exception
    bad_file = tmp_path / "bad.sql"
    bad_file.write_text("dummy", encoding="utf-8")
    model_read_err = ModelRepresentation(
        name="model2",
        path=str(bad_file),
        dialect="postgres",
        query=None,
    )

    from unittest.mock import patch
    with patch("pathlib.Path.read_text", side_effect=IOError("Read error")):
        assert collect_duplicate_cte_findings({"m": model_read_err}, config) == []


def test_duplicate_ctes_parse_exception():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True

    # Invalid SQL syntax that sqlglot cannot parse
    model_invalid_sql = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT FROM WHERE BLA GROUP BY",
    )
    assert collect_duplicate_cte_findings({"m": model_invalid_sql}, config) == []


def test_extract_model_cte_fingerprints_direct():
    from tff.core.checks.duplicate_ctes import extract_model_cte_fingerprints
    import sqlglot

    # 1. None ast_or_sql
    assert extract_model_cte_fingerprints(("m", "m.sql", "duckdb", None, 12)) == []

    # 2. String SQL with complex CTE
    sql = """
    WITH complex_cte AS (
        SELECT id, name FROM users WHERE active = true JOIN orders ON users.id = orders.user_id
    )
    SELECT * FROM complex_cte
    """
    res1 = extract_model_cte_fingerprints(("m1", "m1.sql", "duckdb", sql, 6))
    assert len(res1) == 1
    assert res1[0][1]["cte_name"] == "complex_cte"

    # 3. Parsed Expression with simple CTE (node count < min_nodes)
    simple_sql = "WITH simple_cte AS (SELECT 1) SELECT * FROM simple_cte"
    parsed_simple = sqlglot.parse_one(simple_sql, read="duckdb")
    res2 = extract_model_cte_fingerprints(("m2", "m2.sql", "duckdb", parsed_simple, 15))
    assert len(res2) == 0


def test_duplicate_ctes_parallel_execution():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    cte_logic = """
    WITH shared_logic AS (
        SELECT user_id, SUM(amount) AS total
        FROM ref('stg_orders')
        WHERE status = 'completed'
        GROUP BY 1
    )
    """

    models = {
        f"model_{i}": ModelRepresentation(
            name=f"model_{i}",
            path=f"models/marts/model_{i}.sql",
            dialect="duckdb",
            query=f"{cte_logic} SELECT * FROM shared_logic",
        )
        for i in range(3)
    }

    # Parallel run with max_workers=2
    findings = collect_duplicate_cte_findings(models, config, max_workers=2)
    assert len(findings) == 3
    for f in findings:
        assert f.check == "duplicate_ctes"
        assert "has duplicate transformation logic" in f.message


def test_duplicate_ctes_parallel_fallback():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    cte_logic = """
    WITH shared_logic AS (
        SELECT user_id, SUM(amount) AS total
        FROM ref('stg_orders')
        WHERE status = 'completed'
        GROUP BY 1
    )
    """

    models = {
        f"model_{i}": ModelRepresentation(
            name=f"model_{i}",
            path=f"models/marts/model_{i}.sql",
            dialect="duckdb",
            query=f"{cte_logic} SELECT * FROM shared_logic",
        )
        for i in range(3)
    }

    from unittest.mock import patch
    with patch(
        "tff.core.checks.duplicate_ctes.ProcessPoolExecutor",
        side_effect=RuntimeError("ProcessPool unavailable"),
    ):
        findings = collect_duplicate_cte_findings(models, config, max_workers=2)
        assert len(findings) == 3


def test_duplicate_ctes_empty_and_external():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True

    # Empty
    assert collect_duplicate_cte_findings({}, config) == []

    # Only external / symbolic models
    models = {
        "ext": ModelRepresentation(name="ext", path="ext.sql", dialect="duckdb", is_external=True),
        "sym": ModelRepresentation(name="sym", path="sym.sql", dialect="duckdb", is_symbolic=True),
    }
    assert collect_duplicate_cte_findings(models, config) == []


def test_duplicate_ctes_from_file_path(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    cte_sql = """
    WITH shared_cte AS (
        SELECT id, price * qty AS total
        FROM ref('stg_items')
        WHERE price > 0
    )
    SELECT * FROM shared_cte
    """

    f1 = tmp_path / "m1.sql"
    f2 = tmp_path / "m2.sql"
    f1.write_text(cte_sql, encoding="utf-8")
    f2.write_text(cte_sql, encoding="utf-8")

    m1 = ModelRepresentation(
        name="m1",
        path=str(f1),
        dialect="duckdb",
        query=None,
    )
    m2 = ModelRepresentation(
        name="m2",
        path=str(f2),
        dialect="duckdb",
        query=None,
    )
    m3_missing = ModelRepresentation(
        name="m3_missing",
        path="nonexistent_model_file.sql",
        dialect="duckdb",
        query=None,
    )

    models = {"m1": m1, "m2": m2, "m3": m3_missing}
    findings = collect_duplicate_cte_findings(models, config, max_workers=1)
    assert len(findings) == 2
    assert {f.model for f in findings} == {"m1", "m2"}


