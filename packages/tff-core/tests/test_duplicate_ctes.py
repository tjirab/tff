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


def test_duplicate_ctes_ignored_from_dbt_macros():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    # Compiled SQL has identical complex CTE logic
    compiled_m1 = """
    WITH cleaning_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM stg_users
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT * FROM cleaning_cte
    """
    compiled_m2 = """
    WITH user_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM stg_users
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT id FROM user_cte
    """

    # Raw source code invokes macro
    raw_m1 = """
    WITH cleaning_cte AS (
        {{ clean_users() }}
    )
    SELECT * FROM cleaning_cte
    """
    raw_m2 = """
    WITH user_cte AS (
        {{ clean_users() }}
    )
    SELECT id FROM user_cte
    """

    m1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query=compiled_m1,
        raw_code=raw_m1,
    )
    m2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query=compiled_m2,
        raw_code=raw_m2,
    )

    findings = collect_duplicate_cte_findings({"model1": m1, "model2": m2}, config)
    assert len(findings) == 0


def test_duplicate_ctes_ignored_when_macro_generates_entire_cte():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    compiled_sql = """
    WITH generated_cte AS (
        SELECT id, name, count(*) OVER (PARTITION BY id) AS cnt
        FROM stg_events
        WHERE status = 'processed'
    )
    SELECT * FROM generated_cte
    """

    raw_m1 = "WITH {{ generate_events_cte() }} SELECT * FROM generated_cte"
    raw_m2 = "WITH {{ generate_events_cte() }} SELECT id FROM generated_cte"

    m1 = ModelRepresentation(
        name="m1",
        path="models/m1.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code=raw_m1,
    )
    m2 = ModelRepresentation(
        name="m2",
        path="models/m2.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code=raw_m2,
    )

    findings = collect_duplicate_cte_findings({"m1": m1, "m2": m2}, config)
    assert len(findings) == 0


def test_duplicate_ctes_ignored_from_sqlmesh_macros():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    compiled_sql = """
    WITH cleaning_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM stg_users
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT * FROM cleaning_cte
    """

    raw_m1 = """
    MODEL (name marts.m1);
    WITH cleaning_cte AS (
        @clean_users()
    )
    SELECT * FROM cleaning_cte;
    """
    raw_m2 = """
    MODEL (name marts.m2);
    WITH cleaning_cte AS (
        @clean_users()
    )
    SELECT * FROM cleaning_cte;
    """

    m1 = ModelRepresentation(
        name="m1",
        path="models/m1.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code=raw_m1,
    )
    m2 = ModelRepresentation(
        name="m2",
        path="models/m2.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code=raw_m2,
    )

    findings = collect_duplicate_cte_findings({"m1": m1, "m2": m2}, config)
    assert len(findings) == 0


def test_duplicate_ctes_ignored_from_dataform_macros():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    compiled_sql = """
    WITH cleaning_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM stg_users
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT * FROM cleaning_cte
    """

    raw_m1 = """
    WITH cleaning_cte AS (
        ${cleanUsers()}
    )
    SELECT * FROM cleaning_cte
    """
    raw_m2 = """
    WITH user_cte AS (
        ${cleanUsers()}
    )
    SELECT * FROM user_cte
    """

    m1 = ModelRepresentation(
        name="m1",
        path="definitions/m1.sqlx",
        dialect="bigquery",
        query=compiled_sql,
        raw_code=raw_m1,
    )
    m2 = ModelRepresentation(
        name="m2",
        path="definitions/m2.sqlx",
        dialect="bigquery",
        query=compiled_sql,
        raw_code=raw_m2,
    )

    findings = collect_duplicate_cte_findings({"m1": m1, "m2": m2}, config)
    assert len(findings) == 0


def test_duplicate_ctes_mixed_macro_and_manual_models():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    compiled_sql = """
    WITH cleaning_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM stg_users
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT * FROM cleaning_cte
    """

    # m1 uses macro
    m1 = ModelRepresentation(
        name="m1",
        path="models/m1.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code="WITH cleaning_cte AS ( {{ clean_users() }} ) SELECT * FROM cleaning_cte",
    )
    # m2 also uses macro
    m2 = ModelRepresentation(
        name="m2",
        path="models/m2.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code="WITH cleaning_cte AS ( {{ clean_users() }} ) SELECT * FROM cleaning_cte",
    )
    # m3 copy-pasted the SQL logic manually into its source file
    m3 = ModelRepresentation(
        name="m3",
        path="models/m3.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code="""
        WITH cleaning_cte AS (
            SELECT id, name, LOWER(email) AS clean_email
            FROM {{ ref('stg_users') }}
            WHERE active = TRUE
            ORDER BY id
        )
        SELECT * FROM cleaning_cte
        """,
    )

    models = {"m1": m1, "m2": m2, "m3": m3}
    findings = collect_duplicate_cte_findings(models, config)

    # Only m3 should be flagged because it duplicated manually without the macro
    assert len(findings) == 1
    assert findings[0].model == "m3"
    assert "model 'm1'" in findings[0].message
    assert "model 'm2'" in findings[0].message


def test_duplicate_ctes_config_ignore_macros_disabled():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8
    config.checks.duplicate_ctes.ignore_macros = False

    compiled_sql = """
    WITH cleaning_cte AS (
        SELECT id, name, LOWER(email) AS clean_email
        FROM stg_users
        WHERE active = TRUE
        ORDER BY id
    )
    SELECT * FROM cleaning_cte
    """

    m1 = ModelRepresentation(
        name="m1",
        path="models/m1.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code="WITH cleaning_cte AS ( {{ clean_users() }} ) SELECT * FROM cleaning_cte",
    )
    m2 = ModelRepresentation(
        name="m2",
        path="models/m2.sql",
        dialect="postgres",
        query=compiled_sql,
        raw_code="WITH cleaning_cte AS ( {{ clean_users() }} ) SELECT * FROM cleaning_cte",
    )

    findings = collect_duplicate_cte_findings({"m1": m1, "m2": m2}, config)
    assert len(findings) == 2


def test_duplicate_ctes_from_disk_raw_macro(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    f1 = tmp_path / "m1.sql"
    f2 = tmp_path / "m2.sql"
    f1.write_text("WITH c AS ( {{ my_macro() }} ) SELECT * FROM c", encoding="utf-8")
    f2.write_text("WITH c AS ( {{ my_macro() }} ) SELECT * FROM c", encoding="utf-8")

    compiled_sql = """
    WITH c AS (
        SELECT a, b, SUM(x) AS total FROM tbl WHERE active = 1 GROUP BY a, b
    )
    SELECT * FROM c
    """

    m1 = ModelRepresentation(name="m1", path=str(f1), dialect="duckdb", query=compiled_sql)
    m2 = ModelRepresentation(name="m2", path=str(f2), dialect="duckdb", query=compiled_sql)

    findings = collect_duplicate_cte_findings({"m1": m1, "m2": m2}, config)
    assert len(findings) == 0


def test_duplicate_ctes_not_ignored_if_raw_code_has_full_complex_logic():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    # Raw code has the full complex logic with only a table ref macro
    raw_sql = """
    WITH c AS (
        SELECT a, b, SUM(x) AS total FROM {{ ref('tbl') }} WHERE active = 1 GROUP BY a, b
    )
    SELECT * FROM c
    """
    compiled_sql = """
    WITH c AS (
        SELECT a, b, SUM(x) AS total FROM tbl WHERE active = 1 GROUP BY a, b
    )
    SELECT * FROM c
    """

    m1 = ModelRepresentation(name="m1", path="models/m1.sql", dialect="duckdb", query=compiled_sql, raw_code=raw_sql)
    m2 = ModelRepresentation(name="m2", path="models/m2.sql", dialect="duckdb", query=compiled_sql, raw_code=raw_sql)

    findings = collect_duplicate_cte_findings({"m1": m1, "m2": m2}, config)
    assert len(findings) == 2


def test_extract_paren_content_edge_cases():
    from tff.core.checks.duplicate_ctes import _extract_paren_content

    # Unclosed paren
    assert _extract_paren_content("WITH c AS ( SELECT 1", 10) is None

    # Nested parens with comments and strings
    sql = """WITH c AS (
        -- Comment with ( paren and )
        /* Block with ( and ) */
        SELECT 'quoted ( paren )' AS val, (SELECT 1) AS sub
    ) SELECT * FROM c"""
    open_idx = sql.find("(")
    content = _extract_paren_content(sql, open_idx)
    assert content is not None
    assert "quoted ( paren )" in content
    assert "(SELECT 1)" in content


def test_duplicate_ctes_macro_coverage_edge_cases():
    import sqlglot
    from tff.core.checks.duplicate_ctes import (
        _extract_paren_content,
        extract_model_cte_fingerprints,
        is_cte_produced_by_macro,
    )

    # 1. Paren extraction with escaped quotes
    sql_escapes = r"WITH c AS ( SELECT 'it''s', 'it\'s' ) SELECT * FROM c"
    idx = sql_escapes.find("(")
    assert _extract_paren_content(sql_escapes, idx) is not None

    # 2. is_cte_produced_by_macro with empty raw_sql
    parsed_query = sqlglot.parse_one("SELECT a FROM t WHERE a > 1")
    assert not is_cte_produced_by_macro("c", parsed_query, None, "duckdb", 8)
    assert not is_cte_produced_by_macro("c", parsed_query, "   ", "duckdb", 8)

    # 3. is_cte_produced_by_macro with unclosed paren in raw CTE definition
    unclosed_raw = "WITH c AS ( SELECT {{ my_macro() }} SELECT * FROM c"
    assert not is_cte_produced_by_macro("c", parsed_query, unclosed_raw, "duckdb", 8)

    # 4. is_cte_produced_by_macro when raw CTE body has NO macro, but model has macro elsewhere
    raw_mixed = "WITH c AS ( SELECT a, b FROM t WHERE a > 1 ), m AS ( {{ macro() }} ) SELECT * FROM c"
    assert not is_cte_produced_by_macro("c", parsed_query, raw_mixed, "duckdb", 8)

    # 5. is_cte_produced_by_macro when raw CTE body cleaned syntax has parse error
    raw_parse_err = "WITH c AS ( {{ m() }} SELECT FROM WHERE ) SELECT * FROM c"
    assert is_cte_produced_by_macro("c", parsed_query, raw_parse_err, "duckdb", 8)

    # 6. is_cte_produced_by_macro when raw CTE body cleans to empty/whitespace
    raw_empty_body = "WITH c AS ( {{ m() }} ) SELECT * FROM c"
    from unittest.mock import patch
    with patch("tff.core.ast_cache.parse_sql_with_cache", return_value=None):
        assert is_cte_produced_by_macro("c", parsed_query, raw_empty_body, "duckdb", 8)

    # 7. extract_model_cte_fingerprints with 6-tuple and 7-tuple
    query_sql = "WITH c AS ( SELECT a, b, SUM(x) FROM tbl WHERE a > 1 GROUP BY a, b ) SELECT * FROM c"
    parsed_expr = sqlglot.parse_one(query_sql)
    res_6 = extract_model_cte_fingerprints(("m", "m.sql", "duckdb", parsed_expr, 8, "WITH c AS ( {{ m() }} ) SELECT * FROM c"))
    assert len(res_6) == 1
    assert res_6[0][1]["from_macro"] is True

    res_7 = extract_model_cte_fingerprints(("m", "m.sql", "duckdb", query_sql, 8, "WITH c AS ( {{ m() }} ) SELECT * FROM c", False))
    assert len(res_7) == 1
    assert res_7[0][1]["from_macro"] is False




