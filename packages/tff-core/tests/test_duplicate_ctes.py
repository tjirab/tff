from pathlib import Path

from tff.core.checks.duplicate_ctes import collect_duplicate_cte_findings
from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation


def test_duplicate_ctes_no_duplicates():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    set_ff_config(config)

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
    set_ff_config(config)

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
    assert "has duplicate transformation logic" in findings[0].message


def test_duplicate_ctes_simple_ignored():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    set_ff_config(config)

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
    set_ff_config(config)

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
    set_ff_config(config)

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
    set_ff_config(config)

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
    with patch("tff.core.checks.duplicate_ctes.Path.read_text", side_effect=IOError("Read error")):
        assert collect_duplicate_cte_findings({"m": model_read_err}, config) == []


def test_duplicate_ctes_parse_exception():
    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    set_ff_config(config)

    # Invalid SQL syntax that sqlglot cannot parse
    model_invalid_sql = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT FROM WHERE BLA GROUP BY",
    )
    assert collect_duplicate_cte_findings({"m": model_invalid_sql}, config) == []

