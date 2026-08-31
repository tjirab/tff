"""Integration tests for materialization depth check on dbt."""

from __future__ import annotations

import json
from pathlib import Path

from tff.core.config import ChecksConfig, FitnessFunctionsConfig, MaterializationDepthCheckConfig
from tff.dbt.runner import run_all_checks


def test_dbt_materialization_depth_integration(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    # Create models: source -> view_1 -> view_2 -> view_3 -> view_4 -> view_5
    nodes = {}
    for i in range(1, 6):
        dep = f"model.my_project.view_{i-1}" if i > 1 else "source.my_project.raw_users"
        nodes[f"model.my_project.view_{i}"] = {
            "resource_type": "model",
            "name": f"view_{i}",
            "original_file_path": f"models/view_{i}.sql",
            "columns": {},
            "config": {
                "materialized": "view",
            },
            "depends_on": {
                "nodes": [dep]
            },
        }

    # Add a seed node to manifest
    nodes["seed.my_project.my_seed"] = {
        "resource_type": "seed",
        "name": "my_seed",
        "original_file_path": "seeds/my_seed.csv",
        "columns": {},
        "depends_on": {
            "nodes": []
        }
    }

    manifest_data = {
        "nodes": nodes,
        "sources": {
            "source.my_project.raw_users": {
                "resource_type": "source",
                "name": "raw_users",
                "original_file_path": "models/sources/raw_users.yml",
            }
        },
        "metadata": {
            "adapter_type": "duckdb",
        },
    }

    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Create dummy SQL files
    for i in range(1, 6):
        sql_file = tmp_path / f"models/view_{i}.sql"
        sql_file.parent.mkdir(parents=True, exist_ok=True)
        sql_file.write_text("SELECT 1", encoding="utf-8")

    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=True, max_depth_warn=2, max_depth_fail=3
            )
        )
    )

    findings, checked, selected = run_all_checks(
        project_root=tmp_path, config=config, checks=["materialization_depth"]
    )

    assert "materialization_depth" in selected

    warns = [f for f in findings if f.severity == "warning"]
    errors = [f for f in findings if f.severity == "error"]

    assert len(warns) == 1
    assert warns[0].model == "model.my_project.view_3"

    assert len(errors) == 2
    assert {e.model for e in errors} == {"model.my_project.view_4", "model.my_project.view_5"}

    # Assert seed materialized mapping
    from tff.dbt.manifest import load_dbt_models
    mapped = load_dbt_models(tmp_path)
    assert mapped["seed.my_project.my_seed"].materialized == "seed"


