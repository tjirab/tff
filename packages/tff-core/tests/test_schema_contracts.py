"""Tests for schema contract path resolution."""

from pathlib import Path

import pytest

from tff.core.checks.schema_contracts import _resolve_path


def test_resolve_path_valid_relative(tmp_path: Path) -> None:
    models_dir = tmp_path / "models" / "core"
    models_dir.mkdir(parents=True)
    model_file = models_dir / "dim_customer.sql"
    model_file.write_text("SELECT 1", encoding="utf-8")

    resolved = _resolve_path(tmp_path, "models/core", "dim_customer.sql")

    assert resolved == model_file.resolve()


def test_resolve_path_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="resolves outside project root"):
        _resolve_path(tmp_path, "models", "../../outside.sql")


def test_resolve_path_rejects_absolute_outside_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="resolves outside project root"):
        _resolve_path(tmp_path, "/etc", "passwd")


def test_get_model_sql_and_path(tmp_path: Path) -> None:
    from tff.core.checks.schema_contracts import _get_model_sql_and_path
    from tff.core.model import ModelRepresentation

    # 1. Matched model with query (in-memory, no disk read)
    model_query = ModelRepresentation(
        name="dim_customer",
        path="models/core/dim_customer.sql",
        dialect="duckdb",
        query="SELECT id, name FROM raw_customers",
    )
    models = {"dim_customer": model_query}
    sql, p = _get_model_sql_and_path(tmp_path, "models/core", "dim_customer.sql", models)
    assert sql == "SELECT id, name FROM raw_customers"
    assert p == "models/core/dim_customer.sql"

    # 2. Matched model by stem/clean name with disk file
    model_file = tmp_path / "models" / "core" / "dim_order.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT order_id, amount FROM raw_orders", encoding="utf-8")

    model_disk = ModelRepresentation(
        name="dim_order",
        path=str(model_file),
        dialect="duckdb",
        query="",
    )
    models["dim_order"] = model_disk
    sql, p = _get_model_sql_and_path(tmp_path, "models/core", "dim_order.sql", models)
    assert "SELECT order_id, amount FROM raw_orders" in sql
    assert p == str(model_file)

    # 3. Fallback to disk when not in models
    model_standalone = tmp_path / "models" / "core" / "dim_product.sql"
    model_standalone.write_text("SELECT product_id, sku FROM raw_products", encoding="utf-8")
    sql, p = _get_model_sql_and_path(tmp_path, "models/core", "dim_product.sql", {})
    assert "SELECT product_id, sku FROM raw_products" in sql
    assert p == str(model_standalone.resolve())

    # 4. Not found anywhere
    sql, p = _get_model_sql_and_path(tmp_path, "models/core", "missing.sql", {})
    assert sql is None
    assert p == "missing.sql"

    # 5. Model matched by stem when model.path is empty/unrelated
    model_stem = ModelRepresentation(
        name="stem_model",
        path="",
        dialect="duckdb",
        query="SELECT 1",
    )
    models["stem_model"] = model_stem
    sql, p = _get_model_sql_and_path(tmp_path, "models", "stem_model.sql", models)
    assert sql == "SELECT 1"

    # 6. Escaping path caught by try/except
    sql_esc, p_esc = _get_model_sql_and_path(tmp_path, "models", "../../outside.sql", {})
    assert sql_esc is None
    assert p_esc == "../../outside.sql"


def test_extract_contract_config(tmp_path: Path) -> None:
    import json
    from tff.core.checks.schema_contracts import _extract_contract_config
    from tff.core.config import (
        FitnessFunctionsConfig,
        ChecksConfig,
        SchemaContractsCheckConfig,
        ContractGroupsConfig,
        ColumnParityGroup,
        DimensionParityGroup,
    )

    # 1. From checks.schema_contracts
    cfg1 = FitnessFunctionsConfig(
        checks=ChecksConfig(
            schema_contracts=SchemaContractsCheckConfig(
                column_parity_groups=[
                    ColumnParityGroup(reference="r.sql", members=["m.sql"])
                ],
                dimension_parity_groups=[
                    DimensionParityGroup(left="l.sql", right="r.sql")
                ],
            )
        )
    )
    res1 = _extract_contract_config(cfg1)
    assert len(res1["column_parity_groups"]) == 1
    assert len(res1["dimension_parity_groups"]) == 1

    # 2. From top-level contract_groups
    cfg2 = FitnessFunctionsConfig(
        contract_groups=ContractGroupsConfig(
            column_parity_groups=[
                ColumnParityGroup(reference="r2.sql", members=["m2.sql"])
            ],
            dimension_parity_groups=[
                DimensionParityGroup(left="l2.sql", right="r2.sql")
            ],
        )
    )
    res2 = _extract_contract_config(cfg2)
    assert len(res2["column_parity_groups"]) == 1
    assert len(res2["dimension_parity_groups"]) == 1

    # 3. From legacy JSON file
    legacy_json = tmp_path / "legacy_contracts.json"
    legacy_json.write_text(
        json.dumps({
            "column_parity_groups": [{"reference": "r3.sql", "members": ["m3.sql"]}],
            "dimension_parity_groups": [],
        }),
        encoding="utf-8",
    )
    cfg3 = FitnessFunctionsConfig(contract_groups_path=str(legacy_json))
    cfg3._project_root = tmp_path
    res3 = _extract_contract_config(cfg3)
    assert len(res3["column_parity_groups"]) == 1

    # 4. Empty / missing
    cfg4 = FitnessFunctionsConfig()
    res4 = _extract_contract_config(cfg4)
    assert res4 == {}

    # 5. Corrupt JSON file
    bad_json = tmp_path / "bad_contracts.json"
    bad_json.write_text("invalid json content", encoding="utf-8")
    cfg5 = FitnessFunctionsConfig(contract_groups_path=str(bad_json))
    cfg5._project_root = tmp_path
    res5 = _extract_contract_config(cfg5)
    assert res5 == {}


def test_collect_schema_contract_findings(tmp_path: Path) -> None:
    from tff.core.checks.schema_contracts import collect_schema_contract_findings
    from tff.core.config import (
        FitnessFunctionsConfig,
        ContractGroupsConfig,
        ColumnParityGroup,
        DimensionParityGroup,
    )
    from tff.core.model import ModelRepresentation

    # Set up models:
    # ref: id, name, created_at
    # m1: id, name, created_at (passes column parity)
    # m2: id, name (fails column parity: missing created_at)
    # left: dim_a, dim_b
    # right: dim_a (fails dimension parity: missing dim_b)
    models = {
        "ref": ModelRepresentation(
            name="ref",
            path="models/ref.sql",
            dialect="duckdb",
            query="SELECT\n  id,\n  name,\n  created_at\nFROM t",
        ),
        "m1": ModelRepresentation(
            name="m1",
            path="models/m1.sql",
            dialect="duckdb",
            query="SELECT\n  id,\n  name,\n  created_at\nFROM t1",
        ),
        "m2": ModelRepresentation(
            name="m2",
            path="models/m2.sql",
            dialect="duckdb",
            query="SELECT\n  id,\n  name\nFROM t2",
        ),
        "left": ModelRepresentation(
            name="left",
            path="models/left.sql",
            dialect="duckdb",
            query="SELECT\n  dim_a,\n  dim_b\nFROM tl",
        ),
        "right": ModelRepresentation(
            name="right",
            path="models/right.sql",
            dialect="duckdb",
            query="SELECT\n  dim_a\nFROM tr",
        ),
    }

    config = FitnessFunctionsConfig(
        contract_groups=ContractGroupsConfig(
            column_parity_groups=[
                ColumnParityGroup(
                    reference="models/ref.sql",
                    members=["models/m1.sql", "models/m2.sql"],
                )
            ],
            dimension_parity_groups=[
                DimensionParityGroup(
                    left="models/left.sql",
                    right="models/right.sql",
                )
            ],
        )
    )
    config._project_root = tmp_path

    # Run check with models and config
    findings = collect_schema_contract_findings(models=models, config=config)
    assert len(findings) == 2
    assert any("missing columns" in f.message for f in findings)
    assert any("dimension parity" in f.message or "missing" in f.message for f in findings)

    # Calling with (config) as single argument
    findings_single = collect_schema_contract_findings(config)
    # Without models, it looks on disk and models aren't on disk, so ref not found error
    assert len(findings_single) > 0

    # Missing member and missing ref on column parity
    bad_config = FitnessFunctionsConfig(
        contract_groups=ContractGroupsConfig(
            column_parity_groups=[
                ColumnParityGroup(
                    reference="models/nonexistent_ref.sql",
                    members=["models/m1.sql"],
                ),
                ColumnParityGroup(
                    reference="models/ref.sql",
                    members=["models/nonexistent_member.sql"],
                ),
            ],
            dimension_parity_groups=[
                DimensionParityGroup(
                    left="models/nonexistent_left.sql",
                    right="models/right.sql",
                )
            ],
        )
    )
    bad_config._project_root = tmp_path
    bad_findings = collect_schema_contract_findings(models=models, config=bad_config)
    assert any("nonexistent_ref.sql not found" in f.message for f in bad_findings)
    assert any("nonexistent_member.sql not found" in f.message for f in bad_findings)

    # Calling with no arguments (fallback to default FitnessFunctionsConfig)
    empty_findings = collect_schema_contract_findings()
    assert empty_findings == []
