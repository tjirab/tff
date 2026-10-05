"""Tests for schema contract path resolution and parity checking."""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from conftest import _make_model
from tff.core.checks.schema_contracts import (
    _extract_contract_config,
    _get_model_sql_and_path,
    _resolve_path,
    collect_schema_contract_findings,
)
from tff.core.config import (
    ChecksConfig,
    ColumnParityGroup,
    ContractGroupsConfig,
    DimensionParityGroup,
    FitnessFunctionsConfig,
    SchemaContractsCheckConfig,
)


@pytest.mark.parametrize(
    ("models_dir", "filename", "is_escape"),
    [
        ("models/core", "dim_customer.sql", False),
        ("models", "../../outside.sql", True),
        ("/etc", "passwd", True),
    ],
)
def test_resolve_path(tmp_path: Path, models_dir: str, filename: str, is_escape: bool) -> None:
    if is_escape:
        with pytest.raises(ValueError, match="resolves outside project root"):
            _resolve_path(tmp_path, models_dir, filename)
    else:
        model_file = tmp_path / models_dir / filename
        model_file.parent.mkdir(parents=True, exist_ok=True)
        model_file.write_text("SELECT 1", encoding="utf-8")
        assert _resolve_path(tmp_path, models_dir, filename) == model_file.resolve()


def test_get_model_sql_and_path(tmp_path: Path) -> None:
    # 1. Matched model with in-memory query
    models = {
        "dim_customer": _make_model(
            name="dim_customer",
            path="models/core/dim_customer.sql",
            query="SELECT id, name FROM raw_customers",
        )
    }
    sql, p = _get_model_sql_and_path(tmp_path, "models/core", "dim_customer.sql", models)
    assert sql == "SELECT id, name FROM raw_customers"
    assert p == "models/core/dim_customer.sql"

    # 2. Matched model by stem with disk file
    model_file = tmp_path / "models" / "core" / "dim_order.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT order_id, amount FROM raw_orders", encoding="utf-8")
    models["dim_order"] = _make_model(name="dim_order", path=str(model_file), query="")
    sql, p = _get_model_sql_and_path(tmp_path, "models/core", "dim_order.sql", models)
    assert "SELECT order_id, amount FROM raw_orders" in (sql or "")
    assert p == str(model_file)

    # 3. Fallback to disk when not in models dictionary
    model_standalone = tmp_path / "models" / "core" / "dim_product.sql"
    model_standalone.write_text("SELECT product_id, sku FROM raw_products", encoding="utf-8")
    sql, p = _get_model_sql_and_path(tmp_path, "models/core", "dim_product.sql", {})
    assert "SELECT product_id, sku FROM raw_products" in (sql or "")
    assert p == str(model_standalone.resolve())

    # 4. Not found anywhere
    assert _get_model_sql_and_path(tmp_path, "models/core", "missing.sql", {}) == (None, "missing.sql")

    # 5. Model matched by stem when model.path is empty
    models["stem_model"] = _make_model(name="stem_model", path="", query="SELECT 1")
    sql_stem, _ = _get_model_sql_and_path(tmp_path, "models", "stem_model.sql", models)
    assert sql_stem == "SELECT 1"

    # 6. Escaping path caught safely
    assert _get_model_sql_and_path(tmp_path, "models", "../../outside.sql", {}) == (None, "../../outside.sql")


def test_extract_contract_config(tmp_path: Path) -> None:
    # 1. From checks.schema_contracts
    cfg1 = FitnessFunctionsConfig(
        checks=ChecksConfig(
            schema_contracts=SchemaContractsCheckConfig(
                column_parity_groups=[ColumnParityGroup(reference="r.sql", members=["m.sql"])],
                dimension_parity_groups=[DimensionParityGroup(left="l.sql", right="r.sql")],
            )
        )
    )
    res1 = _extract_contract_config(cfg1)
    assert len(res1["column_parity_groups"]) == 1
    assert len(res1["dimension_parity_groups"]) == 1

    # 2. From top-level contract_groups
    cfg2 = FitnessFunctionsConfig(
        contract_groups=ContractGroupsConfig(
            column_parity_groups=[ColumnParityGroup(reference="r2.sql", members=["m2.sql"])],
            dimension_parity_groups=[DimensionParityGroup(left="l2.sql", right="r2.sql")],
        )
    )
    res2 = _extract_contract_config(cfg2)
    assert len(res2["column_parity_groups"]) == 1
    assert len(res2["dimension_parity_groups"]) == 1

    # 3. From legacy JSON file
    legacy_json = tmp_path / "legacy_contracts.json"
    legacy_json.write_text(
        json.dumps({"column_parity_groups": [{"reference": "r3.sql", "members": ["m3.sql"]}], "dimension_parity_groups": []}),
        encoding="utf-8",
    )
    cfg3 = FitnessFunctionsConfig(contract_groups_path=str(legacy_json))
    cfg3._project_root = tmp_path
    assert len(_extract_contract_config(cfg3)["column_parity_groups"]) == 1

    # 4. Empty and corrupt JSON fallback
    assert _extract_contract_config(FitnessFunctionsConfig()) == {}

    bad_json = tmp_path / "bad_contracts.json"
    bad_json.write_text("invalid json content", encoding="utf-8")
    cfg5 = FitnessFunctionsConfig(contract_groups_path=str(bad_json))
    cfg5._project_root = tmp_path
    assert _extract_contract_config(cfg5) == {}


def test_collect_schema_contract_findings(tmp_path: Path) -> None:
    models = {
        "ref": _make_model(name="ref", path="models/ref.sql", query="SELECT\n  id,\n  name,\n  created_at\nFROM t"),
        "m1": _make_model(name="m1", path="models/m1.sql", query="SELECT\n  id,\n  name,\n  created_at\nFROM t1"),
        "m2": _make_model(name="m2", path="models/m2.sql", query="SELECT\n  id,\n  name\nFROM t2"),
        "left": _make_model(name="left", path="models/left.sql", query="SELECT\n  dim_a,\n  dim_b\nFROM tl"),
        "right": _make_model(name="right", path="models/right.sql", query="SELECT\n  dim_a\nFROM tr"),
    }

    config = FitnessFunctionsConfig(
        contract_groups=ContractGroupsConfig(
            column_parity_groups=[ColumnParityGroup(reference="models/ref.sql", members=["models/m1.sql", "models/m2.sql"])],
            dimension_parity_groups=[DimensionParityGroup(left="models/left.sql", right="models/right.sql")],
        )
    )
    config._project_root = tmp_path

    findings = collect_schema_contract_findings(models=models, config=config)
    assert len(findings) == 2
    assert any("missing columns" in f.message for f in findings)
    assert any("dimension parity" in f.message or "missing" in f.message for f in findings)

    # Calling with config as single positional argument
    assert len(collect_schema_contract_findings(config)) > 0

    # Nonexistent models in config
    bad_config = FitnessFunctionsConfig(
        contract_groups=ContractGroupsConfig(
            column_parity_groups=[
                ColumnParityGroup(reference="models/nonexistent_ref.sql", members=["models/m1.sql"]),
                ColumnParityGroup(reference="models/ref.sql", members=["models/nonexistent_member.sql"]),
            ],
            dimension_parity_groups=[DimensionParityGroup(left="models/nonexistent_left.sql", right="models/right.sql")],
        )
    )
    bad_config._project_root = tmp_path
    bad_findings = collect_schema_contract_findings(models=models, config=bad_config)
    assert any("nonexistent_ref.sql not found" in f.message for f in bad_findings)
    assert any("nonexistent_member.sql not found" in f.message for f in bad_findings)

    # Calling with no arguments
    assert collect_schema_contract_findings() == []
