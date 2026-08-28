import json
from pathlib import Path
from unittest.mock import patch

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
                    "grain": "user_id",  # string grain
                },
                "description": "Staging table for users",
                "depends_on": {"nodes": ["source.my_project.raw_users"]},
            },
            "model.my_project.invalid_grain": {
                "resource_type": "model",
                "name": "invalid_grain",
                "original_file_path": "models/staging/invalid_grain.sql",
                "columns": {},
                "meta": {
                    "grain": 123,  # invalid grain type (neither list nor str)
                },
                "depends_on": {"nodes": []},
            },
            "test.my_project.not_null_stg_users_id": {
                "resource_type": "test",
                "name": "not_null_stg_users_id",
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
                "depends_on": {"nodes": ["model.my_project.stg_users"]},
            },
            "test.my_project.unique_stg_users_id": {
                "resource_type": "test",
                "name": "unique_stg_users_id",
                "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
                "depends_on": {"nodes": ["model.my_project.stg_users"]},
            },
            "test.my_project.no_name_test": {
                "resource_type": "test",
                "name": "no_name_test",
                "test_metadata": {},  # missing name
                "depends_on": {"nodes": ["model.my_project.stg_users"]},
            },
        },
        "sources": {
            "source.my_project.raw_users": {
                "resource_type": "source",
                "name": "raw_users",
                "original_file_path": "models/sources/raw_users.yml",
                "description": "Raw users source table",
                "meta": {"owner": "ingest-team"},
            }
        },
        "metadata": {"adapter_type": "duckdb"},
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
    manifest_data = {"nodes": {}, "sources": {}}
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
                "depends_on": {"nodes": []},
            },
            "model.my_project.symbolic_model": {
                "resource_type": "model",
                "name": "symbolic_model",
                "original_file_path": "models/staging/symbolic.sql",
                "columns": {},
                "config": {"materialized": "ephemeral"},  # symbolic
                "meta": {},
                "depends_on": {"nodes": []},
            },
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
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
    yaml_file.write_text(
        "rules:\n  metadata:\n    enabled: true\n    description: true\n",
        encoding="utf-8",
    )
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
            "depends_on": {"nodes": []},
        },
        "model.my_project.model_config_meta": {
            "resource_type": "model",
            "name": "model_config_meta",
            "original_file_path": "models/staging/model_config_meta.sql",
            "columns": {},
            "config": {
                "materialized": "table",
                "meta": {"owner": "config-owner", "grain": "config-grain"},
            },
            "description": "Model config meta",
            "depends_on": {"nodes": []},
        },
        "model.my_project.model_missing_owner": {
            "resource_type": "model",
            "name": "model_missing_owner",
            "original_file_path": "models/staging/model_missing_owner.sql",
            "columns": {},
            "config": {},
            "meta": {"grain": "user_id"},
            "description": "Missing owner",
            "depends_on": {"nodes": []},
        },
        "model.my_project.model_missing_desc": {
            "resource_type": "model",
            "name": "model_missing_desc",
            "original_file_path": "models/staging/model_missing_desc.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team", "grain": "user_id"},
            "depends_on": {"nodes": []},
        },
        "model.my_project.model_missing_grain": {
            "resource_type": "model",
            "name": "model_missing_grain",
            "original_file_path": "models/staging/model_missing_grain.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team"},
            "description": "Missing grain",
            "depends_on": {"nodes": []},
        },
        "model.my_project.model_missing_not_null": {
            "resource_type": "model",
            "name": "model_missing_not_null",
            "original_file_path": "models/staging/model_missing_not_null.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team", "grain": "user_id"},
            "description": "Missing not null",
            "depends_on": {"nodes": []},
        },
        "model.my_project.model_missing_unique": {
            "resource_type": "model",
            "name": "model_missing_unique",
            "original_file_path": "models/staging/model_missing_unique.sql",
            "columns": {},
            "config": {},
            "meta": {"owner": "data-team", "grain": "user_id"},
            "description": "Missing unique",
            "depends_on": {"nodes": []},
        },
    }

    # Define test node mappings for not_null and unique tests
    test_nodes = {
        # model_ok has both
        "test.my_project.not_null_model_ok_id": {
            "resource_type": "test",
            "name": "not_null_model_ok_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_ok"]},
        },
        "test.my_project.unique_model_ok_id": {
            "resource_type": "test",
            "name": "unique_model_ok_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_ok"]},
        },
        # model_config_meta has both
        "test.my_project.not_null_model_config_meta_id": {
            "resource_type": "test",
            "name": "not_null_model_config_meta_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_config_meta"]},
        },
        "test.my_project.unique_model_config_meta_id": {
            "resource_type": "test",
            "name": "unique_model_config_meta_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_config_meta"]},
        },
        # model_missing_owner has both
        "test.my_project.not_null_model_missing_owner_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_owner_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_owner"]},
        },
        "test.my_project.unique_model_missing_owner_id": {
            "resource_type": "test",
            "name": "unique_model_missing_owner_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_owner"]},
        },
        # model_missing_desc has both
        "test.my_project.not_null_model_missing_desc_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_desc_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_desc"]},
        },
        "test.my_project.unique_model_missing_desc_id": {
            "resource_type": "test",
            "name": "unique_model_missing_desc_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_desc"]},
        },
        # model_missing_grain has both
        "test.my_project.not_null_model_missing_grain_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_grain_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_grain"]},
        },
        "test.my_project.unique_model_missing_grain_id": {
            "resource_type": "test",
            "name": "unique_model_missing_grain_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_grain"]},
        },
        # model_missing_not_null only has unique
        "test.my_project.unique_model_missing_not_null_id": {
            "resource_type": "test",
            "name": "unique_model_missing_not_null_id",
            "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_not_null"]},
        },
        # model_missing_unique only has not_null
        "test.my_project.not_null_model_missing_unique_id": {
            "resource_type": "test",
            "name": "not_null_model_missing_unique_id",
            "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
            "depends_on": {"nodes": ["model.my_project.model_missing_unique"]},
        },
    }

    manifest_data = {
        "nodes": {**models_data, **test_nodes},
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
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
        encoding="utf-8",
    )

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # 1. SQL model with config and source ref
    stg_users_sql = models_dir / "stg_users.sql"
    stg_users_sql.write_text(
        "{{ config(materialized='incremental', owner='data-team', grain=['id']) }}\n"
        "select * from {{ ref('non_existent') }} union all select * from {{ source('raw_sources', 'users') }}\n",
        encoding="utf-8",
    )

    # 2. SQL model with config and model ref
    fct_orders_sql = models_dir / "fct_orders.sql"
    fct_orders_sql.write_text(
        "{{ config(materialized='table', tags=['orders']) }}\n"
        "select * from {{ ref('stg_users') }}\n",
        encoding="utf-8",
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
        encoding="utf-8",
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

    assert stg_users.depends_on == {
        "source.my_test_project.raw_sources.users",
        "model.my_test_project.non_existent",
    }

    fct_orders = models["model.my_test_project.fct_orders"]
    assert fct_orders.name == "fct_orders"
    assert fct_orders.materialized == "table"
    assert fct_orders.tags == ["orders"]
    assert fct_orders.depends_on == {"model.my_test_project.stg_users"}


def test_dbt_dirty_mode_with_git(tmp_path: Path):
    # Create dbt_project.yml
    dbt_project_yml = tmp_path / "dbt_project.yml"
    dbt_project_yml.write_text(
        "name: 'git_test'\nversion: '1.0.0'\nmodel-paths: ['models']\n",
        encoding="utf-8",
    )

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    # stg_users is clean (committed)
    stg_users_sql = models_dir / "stg_users.sql"
    stg_users_sql.write_text(
        "{{ config(materialized='view') }}\nselect * from some_table", encoding="utf-8"
    )

    # fct_orders.sql is dirty (untracked)
    fct_orders_sql = models_dir / "fct_orders.sql"
    fct_orders_sql.write_text(
        "{{ config(materialized='table', owner='orders-team') }}\n"
        "select * from {{ ref('stg_users') }}",
        encoding="utf-8",
    )

    from tff.dbt.manifest import load_dbt_models
    from tff.dbt.runner import run_all_checks

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
                "depends_on": {"nodes": []},
            }
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
    }
    (target_dir / "manifest.json").write_text(
        json.dumps(manifest_data), encoding="utf-8"
    )

    # Run load_dbt_models in dirty mode with mocked get_dirty_files
    with (
        patch("tff.dbt.manifest.get_dirty_files") as mock_get_files,
        patch("tff.dbt.manifest.get_dirty_model_names") as mock_get_names,
    ):
        mock_get_files.return_value = [fct_orders_sql]
        mock_get_names.return_value = {"fct_orders"}

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
        mock_get_names.return_value = {"fct_orders", "stg_users"}
        mock_get_files.return_value = [fct_orders_sql, stg_users_sql]

        # We need to reload/overlay models
        models = load_dbt_models(tmp_path, dirty=True, dialect="duckdb")

        # Now mock the checks runner to check both
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


@patch("subprocess.run")
def test_git_dirty_files_mocked(mock_run):
    from unittest.mock import MagicMock, mock_open
    from tff.dbt.manifest import get_dirty_files, get_dirty_model_names

    # 1. Test get_dirty_files success
    mock_git_root = MagicMock()
    mock_git_root.stdout = "/workspace/project\n"
    mock_git_status = MagicMock()
    mock_git_status.stdout = (
        " M models/stg_users.sql\n"
        "?? seeds/my_seed.csv\n"
        "?? models/schema.yml\n"
        " R old.sql -> models/new.sql\n"
        '?? "models/quoted.sql"\n'
        " M root_file.txt\n"
    )
    mock_run.side_effect = [mock_git_root, mock_git_status]

    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("pathlib.Path.is_file", return_value=True),
    ):
        dirty = get_dirty_files(Path("/workspace/project"))
        names = [f.name for f in dirty]
        assert "stg_users.sql" in names
        assert "my_seed.csv" in names
        assert "schema.yml" in names
        assert "new.sql" in names
        assert "quoted.sql" in names
        assert "root_file.txt" not in names

    # 2. Test get_dirty_files exception
    mock_run.side_effect = Exception("git failed")
    import pytest

    with pytest.raises(RuntimeError, match="Failed to detect git repository"):
        get_dirty_files(Path("/workspace/project"))

    # 3. Test get_dirty_model_names exceptions / coverage
    with patch("builtins.open", side_effect=Exception("Read error")):
        names = get_dirty_model_names([Path("schema.yml")], Path("."))
        assert names == set()

    # 4. Test get_dirty_model_names success with SQL and YML files
    sql_file = Path("models/my_model.sql")
    yml_file = Path("models/schema.yml")
    yml_content = "models:\n  - name: my_model\nseeds:\n  - name: my_seed\n"
    with patch("builtins.open", mock_open(read_data=yml_content)):
        names = get_dirty_model_names([sql_file, yml_file], Path("."))
        assert names == {"my_model", "my_seed"}


def test_dbt_project_config_coverage_booster():
    from unittest.mock import mock_open
    from tff.dbt.manifest import _parse_dbt_project_config

    # Mock string paths in dbt_project.yml
    dbt_config_str = (
        "name: 'string_project'\nmodel-paths: 'my_models'\nseed-paths: 'my_seeds'\n"
    )
    with (
        patch("pathlib.Path.exists", return_value=True),
        patch("builtins.open", mock_open(read_data=dbt_config_str)),
    ):
        proj_name, model_paths, seed_paths = _parse_dbt_project_config(Path("."))
        assert proj_name == "string_project"
        assert model_paths == ["my_models"]
        assert seed_paths == ["my_seeds"]


def test_dbt_sql_parsing_coverage_booster(tmp_path: Path):
    from tff.dbt.manifest import parse_dbt_sql_file

    # SQL model with package ref, string grain, and string tag
    sql_file = tmp_path / "my_model.sql"
    sql_file.write_text(
        "{{ config(materialized='ephemeral', tags='tag1', grain='id') }}\n"
        "select * from {{ ref('other_pkg', 'other_model') }}\n",
        encoding="utf-8",
    )

    rep = parse_dbt_sql_file(sql_file, tmp_path, "proj", "duckdb")
    assert rep.name == "my_model"
    assert rep.materialized == "ephemeral"
    assert rep.is_symbolic is True
    assert rep.tags == ["tag1"]
    assert rep.grains == ["id"]
    assert rep.meta["_raw_refs"] == [("other_pkg", "other_model")]


def test_dbt_yml_parsing_coverage_booster(tmp_path: Path):
    from tff.dbt.manifest import parse_dbt_yml_file, ModelRepresentation

    # Setup loaded models
    models = {
        "model.proj.my_model": ModelRepresentation(
            name="my_model",
            path=str(tmp_path / "my_model.sql"),
            dialect="duckdb",
        ),
        "model.proj.other_model": ModelRepresentation(
            name="other_model",
            path=str(tmp_path / "other_model.sql"),
            dialect="duckdb",
        ),
    }

    # YAML containing string tags, list grain, source owner, column tests, model-level tests
    yml_file = tmp_path / "schema.yml"
    yml_file.write_text(
        "version: 2\n"
        "models:\n"
        "  - name: my_model\n"
        "    tags: 'model_tag'\n"
        "    config:\n"
        "      materialized: ephemeral\n"
        "      owner: 'model_owner'\n"
        "      grain: 'model_grain'\n"
        "    columns:\n"
        "      - name: id\n"
        "        data_type: INT\n"
        "        tests:\n"
        "          - unique:\n"
        "              column_name: id\n"
        "          - not_null\n"
        "      - name: not_a_dict_col\n"
        "      - 'not_a_dict_col2'\n"
        "    tests:\n"
        "      - 'model_test_str'\n"
        "      - my_test_dict:\n"
        "          arg: 1\n"
        "      - 'unique'\n"
        "      - 'not_a_valid_test_type_list': [1,2]\n"
        "  - name: other_model\n"
        "    config:\n"
        "      grain:\n"
        "        - id\n"
        "  - name: non_existent_model\n"
        "  - 'not_a_dict'\n"
        "sources:\n"
        "  - name: my_source\n"
        "    tags: 'src_tag'\n"
        "    meta:\n"
        "      owner: 'src_owner'\n"
        "    tables:\n"
        "      - name: my_table\n"
        "        tags: 'tbl_tag'\n"
        "        meta:\n"
        "          owner: 'tbl_owner'\n"
        "        description: 'Source table'\n"
        "      - 'not_a_dict_table'\n"
        "  - 'not_a_dict_source'\n",
        encoding="utf-8",
    )

    parse_dbt_yml_file(yml_file, "proj", "duckdb", models)

    # Assert model updates
    model = models["model.proj.my_model"]
    assert model.tags == ["model_tag"]
    assert model.owner == "model_owner"
    assert model.grains == ["model_grain"]
    assert model.materialized == "ephemeral"
    assert model.is_symbolic is True
    assert model.columns_to_types == {"id": "int"}

    other_model = models["model.proj.other_model"]
    assert other_model.grains == ["id"]

    audits = [name for name, _ in model.audits]
    assert "unique_values" in audits
    assert "not_null" in audits
    assert "model_test_str" in audits
    assert "my_test_dict" in audits

    # Assert source creation
    src_tbl_id = "source.proj.my_source.my_table"
    assert src_tbl_id in models
    src = models[src_tbl_id]
    assert src.name == "my_table"
    assert "src_tag" in src.tags
    assert "tbl_tag" in src.tags
    assert src.owner == "tbl_owner"
    assert src.description == "Source table"


def test_dbt_dirty_mode_extra_coverage(tmp_path: Path):
    # Create dbt_project.yml
    dbt_project_yml = tmp_path / "dbt_project.yml"
    dbt_project_yml.write_text(
        "name: 'cov_test'\nversion: '1.0.0'\nmodel-paths: ['models']\nseed-paths: ['seeds']\n",
        encoding="utf-8",
    )

    models_dir = tmp_path / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    seeds_dir = tmp_path / "seeds"
    seeds_dir.mkdir(parents=True, exist_ok=True)

    # Baseline models/seeds
    baseline_sql = models_dir / "baseline.sql"
    baseline_sql.write_text("select 1", encoding="utf-8")

    # A dirty SQL referencing a seed and a source
    dirty_sql = models_dir / "dirty_model.sql"
    dirty_sql.write_text(
        "{{ config(materialized='table') }}\n"
        "select * from {{ ref('my_seed') }} union all select * from {{ source('my_src', 'my_tbl') }}",
        encoding="utf-8",
    )

    # A dirty seed (.csv file)
    dirty_seed = seeds_dir / "my_seed.csv"
    dirty_seed.write_text("id,val\n1,one", encoding="utf-8")

    # A second dirty seed that is NOT in the baseline manifest (covers the new seed overlay branch)
    new_seed = seeds_dir / "new_seed.csv"
    new_seed.write_text("id,val\n2,two", encoding="utf-8")

    # A dirty YAML file defining model description, tests, and sources
    dirty_yml = models_dir / "schema.yml"
    dirty_yml.write_text(
        "version: 2\n"
        "models:\n"
        "  - name: dirty_model\n"
        "    description: 'A dirty model'\n"
        "    tests:\n"
        "      - unique:\n"
        "          column_name: id\n"
        "sources:\n"
        "  - name: my_src\n"
        "    tables:\n"
        "      - name: my_tbl\n"
        "        meta:\n"
        "          owner: 'src-owner'\n",
        encoding="utf-8",
    )

    from tff.dbt.manifest import load_dbt_models

    # Mock get_dirty_files to return dirty files deterministically
    with patch("tff.dbt.manifest.get_dirty_files") as mock_get:
        mock_get.return_value = [dirty_sql, dirty_seed, new_seed, dirty_yml]

        # Run load_dbt_models in dirty mode with NO manifest.json on disk!
        # This covers the fallback loader in dirty mode
        models = load_dbt_models(tmp_path, dirty=True, dialect="duckdb")

        assert "model.cov_test.dirty_model" in models
        assert "seed.cov_test.my_seed" in models
        assert "seed.cov_test.new_seed" in models
        assert "source.cov_test.my_src.my_tbl" in models

        dirty_model = models["model.cov_test.dirty_model"]
        assert "seed.cov_test.my_seed" in dirty_model.depends_on
        assert "source.cov_test.my_src.my_tbl" in dirty_model.depends_on

        # Now mock manifest.json exists so we exercise overlay logic for YAML, seeds, and SQL
        target_dir = tmp_path / "target"
        target_dir.mkdir(exist_ok=True)
        manifest_data = {
            "nodes": {
                "model.cov_test.baseline": {
                    "resource_type": "model",
                    "name": "baseline",
                    "original_file_path": "models/baseline.sql",
                    "columns": {},
                    "config": {"materialized": "view"},
                    "meta": {},
                    "depends_on": {"nodes": []},
                },
                "seed.cov_test.my_seed": {
                    "resource_type": "seed",
                    "name": "my_seed",
                    "original_file_path": "seeds/my_seed.csv",
                    "columns": {},
                    "config": {},
                    "meta": {},
                    "depends_on": {"nodes": []},
                },
            },
            "sources": {},
            "metadata": {"adapter_type": "duckdb"},
        }
        (target_dir / "manifest.json").write_text(
            json.dumps(manifest_data), encoding="utf-8"
        )

        # Mock get_dirty_files to return baseline_sql and dirty_seed so they trigger existing path matches!
        mock_get.return_value = [
            baseline_sql,
            dirty_sql,
            dirty_seed,
            new_seed,
            dirty_yml,
        ]

        # Run load_dbt_models in dirty mode with manifest.json on disk!
        models2 = load_dbt_models(tmp_path, dirty=True, dialect="duckdb")
        assert "model.cov_test.baseline" in models2
        assert "model.cov_test.dirty_model" in models2
        assert "seed.cov_test.my_seed" in models2
        assert "seed.cov_test.new_seed" in models2
        assert "source.cov_test.my_src.my_tbl" in models2

        dirty_model2 = models2["model.cov_test.dirty_model"]
        assert dirty_model2.description == "A dirty model"
        assert "seed.cov_test.my_seed" in dirty_model2.depends_on
        assert "source.cov_test.my_src.my_tbl" in dirty_model2.depends_on
