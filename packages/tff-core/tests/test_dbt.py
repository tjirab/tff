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
            "test.my_project.unique_stg_users_id": {
                "resource_type": "test",
                "name": "unique_stg_users_id",
                "test_metadata": {
                    "name": "unique",
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
        },
        "metadata": {
            "adapter_type": "duckdb"
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
    assert len(user_model.audits) == 2
    assert ("not_null", {"column_name": "id"}) in user_model.audits
    assert ("unique_values", {"column_name": "id"}) in user_model.audits
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


def test_load_dbt_models_missing_dialect(tmp_path: Path):
    import pytest
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"
    manifest_data = {
        "nodes": {},
        "sources": {}
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")
    
    with pytest.raises(ValueError, match="SQL dialect could not be determined"):
        load_dbt_models(tmp_path)


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
        "sources": {},
        "metadata": {
            "adapter_type": "duckdb"
        }
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


def test_dbt_metadata_checks_coverage(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    # Define test models
    models_data = {
        "model.my_project.model_ok": {
            "resource_type": "model",
            "name": "model_ok",
            "original_file_path": "models/staging/model_ok.sql",
            "columns": {},
            "config": {"materialized": "table"},
            "meta": {"owner": "data-team", "grain": "user_id"},
            "description": "An okay model",
            "depends_on": {"nodes": []}
        },
        "model.my_project.model_config_meta": {
            "resource_type": "model",
            "name": "model_config_meta",
            "original_file_path": "models/staging/model_config_meta.sql",
            "columns": {},
            "config": {
                "materialized": "table",
                "meta": {"owner": "config-owner", "grain": "config-grain"}
            },
            "description": "Model config meta",
            "depends_on": {"nodes": []}
        },
        "model.my_project.model_missing_owner": {
            "resource_type": "model",
            "name": "model_missing_owner",
            "original_file_path": "models/staging/model_missing_owner.sql",
            "columns": {},
            "config": {},
            "meta": {"grain": "user_id"},
            "description": "Missing owner",
            "depends_on": {"nodes": []}
        },
        "model.my_project.model_missing_desc": {
            "resource_type": "model",
            "name": "model_missing_desc",
            "original_file_path": "models/staging/model_missing_desc.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team", "grain": "user_id"},
            "depends_on": {"nodes": []}
        },
        "model.my_project.model_missing_grain": {
            "resource_type": "model",
            "name": "model_missing_grain",
            "original_file_path": "models/staging/model_missing_grain.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team"},
            "description": "Missing grain",
            "depends_on": {"nodes": []}
        },
        "model.my_project.model_missing_not_null": {
            "resource_type": "model",
            "name": "model_missing_not_null",
            "original_file_path": "models/staging/model_missing_not_null.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team", "grain": "user_id"},
            "description": "Missing not null",
            "depends_on": {"nodes": []}
        },
        "model.my_project.model_missing_unique": {
            "resource_type": "model",
            "name": "model_missing_unique",
            "original_file_path": "models/staging/model_missing_unique.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team", "grain": "user_id"},
            "description": "Missing unique",
            "depends_on": {"nodes": []}
        }
    }

    # Define test node mappings for not_null and unique tests
    test_nodes = {
        # model_ok has both
        "test.my_project.not_null_model_ok_id": {
            "resource_type": "test",
            "name": "not_null_model_ok_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_ok"]}
        },
        "test.my_project.unique_model_ok_id": {
            "resource_type": "test",
            "name": "unique_model_ok_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_ok"]}
        },
        # model_config_meta has both
        "test.my_project.not_null_model_config_meta_id": {
            "resource_type": "test",
            "name": "not_null_model_config_meta_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_config_meta"]}
        },
        "test.my_project.unique_model_config_meta_id": {
            "resource_type": "test",
            "name": "unique_model_config_meta_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_config_meta"]}
        },
        # model_missing_owner has both
        "test.my_project.not_null_model_missing_owner_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_owner_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_owner"]}
        },
        "test.my_project.unique_model_missing_owner_id": {
            "resource_type": "test",
            "name": "unique_model_missing_owner_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_owner"]}
        },
        # model_missing_desc has both
        "test.my_project.not_null_model_missing_desc_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_desc_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_desc"]}
        },
        "test.my_project.unique_model_missing_desc_id": {
            "resource_type": "test",
            "name": "unique_model_missing_desc_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_desc"]}
        },
        # model_missing_grain has both
        "test.my_project.not_null_model_missing_grain_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_grain_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_grain"]}
        },
        "test.my_project.unique_model_missing_grain_id": {
            "resource_type": "test",
            "name": "unique_model_missing_grain_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_grain"]}
        },
        # model_missing_not_null only has unique
        "test.my_project.unique_model_missing_not_null_id": {
            "resource_type": "test",
            "name": "unique_model_missing_not_null_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_not_null"]}
        },
        # model_missing_unique only has not_null
        "test.my_project.not_null_model_missing_unique_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_unique_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_unique"]}
        }
    }

    manifest_data = {
        "nodes": {**models_data, **test_nodes},
        "sources": {},
        "metadata": {
            "adapter_type": "duckdb"
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    # Write dummy SQL files for path resolution
    for key, value in models_data.items():
        rel_path = value["original_file_path"]
        sql_file = tmp_path / rel_path
        sql_file.parent.mkdir(parents=True, exist_ok=True)
        sql_file.write_text("select 1", encoding="utf-8")

    # Load fitness config with all metadata rules enabled
    config = FitnessFunctionsConfig()
    config.rules.metadata.enabled = True
    config.rules.metadata.owner = True
    config.rules.metadata.description = True
    config.rules.metadata.grain = True
    config.rules.metadata.not_null = True
    config.rules.metadata.unique_values = True

    findings, models_checked, selected = run_all_checks(
        project_root=tmp_path,
        config=config,
    )

    # We checked 7 models
    assert models_checked == 7

    # Group findings by model name for easy assertion
    findings_by_model: dict[str, list[str]] = {}
    for f in findings:
        if f.model not in findings_by_model:
            findings_by_model[f.model] = []
        findings_by_model[f.model].append(f.check)

    # Assert model_ok and model_config_meta have no findings
    assert "model_ok" not in findings_by_model
    assert "model_config_meta" not in findings_by_model

    # Assert specific rule violations
    assert findings_by_model["model_missing_owner"] == ["nomissingowner"]
    assert findings_by_model["model_missing_desc"] == ["nomissingdescription"]
    assert findings_by_model["model_missing_grain"] == ["nomissinggrain"]
    assert findings_by_model["model_missing_not_null"] == ["nomissingnotnull"]
    assert findings_by_model["model_missing_unique"] == ["nomissinguniquevalues"]


def test_load_dbt_models_fallback(tmp_path: Path):
    # Create dbt_project.yml
    dbt_project_yml = tmp_path / "dbt_project.yml"
    dbt_project_yml.write_text(
        "name: 'my_test_project'\nversion: '1.0.0'\nmodel-paths: ['models']\nseed-paths: ['seeds']\n",
        encoding="utf-8"
    )

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # 1. SQL model with config and source ref
    stg_users_sql = models_dir / "stg_users.sql"
    stg_users_sql.write_text(
        "{{ config(materialized='incremental', owner='data-team', grain=['id']) }}\n"
        "select * from {{ source('raw_sources', 'users') }}\n",
        encoding="utf-8"
    )

    # 2. SQL model with config and model ref
    fct_orders_sql = models_dir / "fct_orders.sql"
    fct_orders_sql.write_text(
        "{{ config(materialized='table', tags=['orders']) }}\n"
        "select * from {{ ref('stg_users') }}\n",
        encoding="utf-8"
    )

    # 3. schema.yml with metadata and tests
    schema_yml = models_dir / "schema.yml"
    schema_yml.write_text(
        "version: 2\n"
        "models:\n"
        "  - name: stg_users\n"
        "    description: 'Staging users'\n"
        "    columns:\n"
        "      - name: id\n"
        "        data_type: integer\n"
        "        tests:\n"
        "          - unique\n"
        "          - not_null\n"
        "sources:\n"
        "  - name: raw_sources\n"
        "    tables:\n"
        "      - name: users\n"
        "        description: 'Raw users data'\n",
        encoding="utf-8"
    )

    from tff.dbt.manifest import load_dbt_models_fallback

    models = load_dbt_models_fallback(tmp_path, dialect="duckdb")

    # Assertions
    assert "model.my_test_project.stg_users" in models
    assert "model.my_test_project.fct_orders" in models
    assert "source.my_test_project.raw_sources.users" in models

    stg_users = models["model.my_test_project.stg_users"]
    assert stg_users.name == "stg_users"
    assert stg_users.materialized == "incremental"
    assert stg_users.owner == "data-team"
    assert stg_users.grains == ["id"]
    assert stg_users.description == "Staging users"
    assert stg_users.columns_to_types == {"id": "integer"}
    
    audits = {name for name, _ in stg_users.audits}
    assert "unique_values" in audits
    assert "not_null" in audits

    assert stg_users.depends_on == {"source.my_test_project.raw_sources.users"}

    fct_orders = models["model.my_test_project.fct_orders"]
    assert fct_orders.name == "fct_orders"
    assert fct_orders.materialized == "table"
    assert fct_orders.tags == ["orders"]
    assert fct_orders.depends_on == {"model.my_test_project.stg_users"}


def test_dbt_dirty_mode_with_git(tmp_path: Path):
    import subprocess
    
    # Initialize a git repo in tmp_path
    try:
        subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
        # Configure dummy user
        subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    except Exception:
        import pytest
        pytest.skip("Git CLI not available for test")

    # Create dbt_project.yml
    dbt_project_yml = tmp_path / "dbt_project.yml"
    dbt_project_yml.write_text(
        "name: 'git_test'\nversion: '1.0.0'\nmodel-paths: ['models']\n",
        encoding="utf-8"
    )

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # stg_users is clean (committed)
    stg_users_sql = models_dir / "stg_users.sql"
    stg_users_sql.write_text(
        "{{ config(materialized='view') }}\nselect * from some_table",
        encoding="utf-8"
    )
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=tmp_path, check=True)

    # fct_orders.sql is dirty (untracked)
    fct_orders_sql = models_dir / "fct_orders.sql"
    fct_orders_sql.write_text(
        "{{ config(materialized='table', owner='orders-team') }}\n"
        "select * from {{ ref('stg_users') }}",
        encoding="utf-8"
    )

    from tff.dbt.manifest import get_dirty_files, get_dirty_model_names, load_dbt_models
    from tff.dbt.runner import run_all_checks

    dirty_files = get_dirty_files(tmp_path)
    assert len(dirty_files) == 1
    assert dirty_files[0].name == "fct_orders.sql"

    dirty_names = get_dirty_model_names(dirty_files, tmp_path)
    assert dirty_names == {"fct_orders"}

    # Mock a target/manifest.json that only has stg_users
    target_dir = tmp_path / "target"
    target_dir.mkdir(exist_ok=True)
    manifest_data = {
        "nodes": {
            "model.git_test.stg_users": {
                "resource_type": "model",
                "name": "stg_users",
                "original_file_path": "models/stg_users.sql",
                "columns": {},
                "config": {"materialized": "view"},
                "meta": {},
                "depends_on": {"nodes": []}
            }
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"}
    }
    (target_dir / "manifest.json").write_text(json.dumps(manifest_data), encoding="utf-8")

    # Run load_dbt_models in dirty mode - it should load stg_users from manifest and fct_orders from fallback!
    models = load_dbt_models(tmp_path, dirty=True, dialect="duckdb")
    assert "model.git_test.stg_users" in models
    assert "model.git_test.fct_orders" in models

    fct_orders = models["model.git_test.fct_orders"]
    assert fct_orders.owner == "orders-team"
    assert fct_orders.depends_on == {"model.git_test.stg_users"}

    # Run run_all_checks in dirty mode
    config = FitnessFunctionsConfig()
    config.rules.metadata.enabled = True
    config.rules.metadata.owner = True
    config.rules.metadata.description = False
    config.rules.metadata.grain = False
    config.rules.metadata.not_null = False
    config.rules.metadata.unique_values = False

    # Should only run checks and report findings on fct_orders (the dirty model)
    findings, models_checked, selected = run_all_checks(
        project_root=tmp_path,
        config=config,
        dialect="duckdb",
        dirty=True,
    )
    # Only fct_orders was dirty and checked
    assert models_checked == 1
    # owner is set, so 0 findings
    assert len(findings) == 0

    # Let's make stg_users dirty by adding owner violation
    stg_users_sql.write_text(
        "{{ config(materialized='view') }}\nselect * from some_table -- modified",
        encoding="utf-8"
    )
    findings, models_checked, selected = run_all_checks(
        project_root=tmp_path,
        config=config,
        dialect="duckdb",
        dirty=True,
    )
    # Both stg_users and fct_orders are now dirty
    assert models_checked == 2
    # stg_users is missing owner -> 1 finding
    assert len(findings) == 1
    assert findings[0].model == "stg_users"
    assert findings[0].check == "nomissingowner"



