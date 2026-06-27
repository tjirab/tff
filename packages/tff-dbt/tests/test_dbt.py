import json
from pathlib import Path

from tff.dbt.manifest import load_dbt_models
from tff.dbt.runner import run_all_checks
from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config


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
                },
                "description": "Staging table for users",
                "depends_on": {
                    "nodes": ["source.my_project.raw_users"]
                }
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

    source_node = models["source.my_project.raw_users"]
    assert source_node.name == "raw_users"
    assert source_node.is_external is True
    assert source_node.owner == "ingest-team"
