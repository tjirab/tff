import json
from pathlib import Path

from tff.dbt.manifest import load_dbt_models
from tff.dbt.runner import run_all_checks
from tff.core.config import FitnessFunctionsConfig


def test_load_dbt_models(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    # Mock a simple manifest.json structure
    manifest_data = {
        "nodes": {
            "model.my_project.stg_users": {
                "resource_type": "model",
                "name": "stg_users",
                "original_file_path": "models/staging/stg_users.sql",
                "columns": {
                    "id": {"data_type": "INT"},
                    "name": {"data_type": "VARCHAR"},
                },
                "config": {
                    "materialized": "view",
                },
                "meta": {
                    "owner": "data-team",
                    "grain": "user_id", # string grain
                },
                "description": "Staging table for users",
                "depends_on": {
                    "nodes": ["source.my_project.raw_users"]
                }
            },
            "model.my_project.invalid_grain": {
                "resource_type": "model",
                "name": "invalid_grain",
                "original_file_path": "models/staging/invalid_grain.sql",
                "columns": {},
                "meta": {
                    "grain": 123, # invalid grain type (neither list nor str)
                },
                "depends_on": {"nodes": []}
            },
            "test.my_project.not_null_stg_users_id": {
                "resource_type": "test",
                "name": "not_null_stg_users_id",
                "test_metadata": {
                    "name": "not_null",
                    "kwargs": {"column_name": "id"}
                },
                "depends_on": {
                    "nodes": ["model.my_project.stg_users"]
                }
            },
            "test.my_project.no_name_test": {
                "resource_type": "test",
                "name": "no_name_test",
                "test_metadata": {}, # missing name
                "depends_on": {
                    "nodes": ["model.my_project.stg_users"]
                }
            }
        },
        "sources": {
            "source.my_project.raw_users": {
                "resource_type": "source",
                "name": "raw_users",
                "original_file_path": "models/sources/raw_users.yml",
                "description": "Raw users source table",
                "meta": {"owner": "ingest-team"}
            }
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dbt_models(tmp_path)
    assert "model.my_project.stg_users" in models
    assert "source.my_project.raw_users" in models

    user_model = models["model.my_project.stg_users"]
    assert user_model.name == "stg_users"
    assert user_model.columns_to_types == {"id": "int", "name": "varchar"}
    assert user_model.owner == "data-team"
    assert user_model.description == "Staging table for users"
    assert user_model.depends_on == {"source.my_project.raw_users"}
    assert user_model.audits == [("not_null", {"column_name": "id"})]
    assert user_model.grains == ["user_id"]

    invalid_grain_model = models["model.my_project.invalid_grain"]
    assert invalid_grain_model.grains == []

    source_node = models["source.my_project.raw_users"]
    assert source_node.name == "raw_users"
    assert source_node.is_external is True
    assert source_node.owner == "ingest-team"


def test_load_dbt_models_missing_manifest():
    import pytest
    with pytest.raises(FileNotFoundError):
        load_dbt_models(Path("/non_existent_path"))


def test_run_all_checks(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    # Mock manifest with standard model, symbolic model, and external source
    manifest_data = {
        "nodes": {
            "model.my_project.stg_users": {
                "resource_type": "model",
                "name": "stg_users",
                "original_file_path": "models/staging/stg_users.sql",
                "columns": {
                    "id": {"data_type": "INT"},
                },
                "config": {},
                "meta": {"owner": "data-team"},
                "depends_on": {"nodes": []}
            },
            "model.my_project.symbolic_model": {
                "resource_type": "model",
                "name": "symbolic_model",
                "original_file_path": "models/staging/symbolic.sql",
                "columns": {},
                "config": {"materialized": "ephemeral"}, # symbolic
                "meta": {},
                "depends_on": {"nodes": []}
            }
        },
        "sources": {}
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Mock SQL files
    sql_file = tmp_path / "models/staging/stg_users.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT id FROM raw", encoding="utf-8")

    # 1. Test passing config explicitly
    config = FitnessFunctionsConfig()
    config.rules.metadata.enabled = True
    config.rules.metadata.owner = True
    config.rules.metadata.description = True  # will violate

    findings, models_checked, selected = run_all_checks(
        project_root=tmp_path,
        config=config,
    )
    assert models_checked == 1  # symbolic is skipped
    assert len(findings) > 0
    assert any("description" in f.check for f in findings)

    # 2. Test running with config=None (auto-discovers config file)
    yaml_file = tmp_path / "fitness_functions.yaml"
    yaml_file.write_text("rules:\n  metadata:\n    enabled: true\n    description: true\n", encoding="utf-8")
    findings_auto, _, _ = run_all_checks(
        project_root=tmp_path,
        config=None,
    )
    assert len(findings_auto) > 0

    # 3. Test specifying checks list explicitly
    findings_subset, _, selected_subset = run_all_checks(
        project_root=tmp_path,
        config=config,
        checks=["rules"],
    )
    assert selected_subset == ["rules"]
    assert len(findings_subset) > 0

