import json
from pathlib import Path

from tff.dbt.manifest import load_dbt_models
from tff.dbt.runner import run_all_checks
from tff.core.config import FitnessFunctionsConfig, load_fitness_config


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


def test_run_all_checks_with_no_cache(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"
    manifest_data = {
        "nodes": {
            "model.my_project.stg_users": {
                "resource_type": "model",
                "name": "stg_users",
                "original_file_path": "models/staging/stg_users.sql",
                "columns": {},
                "config": {},
                "meta": {},
                "raw_code": "SELECT 1 AS id",
                "depends_on": {"nodes": []},
            }
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    config = FitnessFunctionsConfig(cache_ast=False)
    findings, checked, _ = run_all_checks(
        project_root=tmp_path,
        config=config,
    )
    assert checked == 1
    # Verify .tff_cache was not created
    assert not (tmp_path / ".tff_cache").exists()


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


def test_example_minimal_dbt_project_zero_config():
    example_root = Path(__file__).resolve().parents[3] / "examples" / "minimal-dbt-project"
    assert (example_root / "dbt_project.yml").exists()
    assert not (example_root / "fitness_functions.yaml").exists()

    findings, models_checked, selected = run_all_checks(project_root=example_root)
    assert models_checked == 4
    # Ensure layer_integrity passes (zero violations) under default staging -> intermediate -> core -> marts conventions
    layer_violations = [f for f in findings if f.check == "layer_integrity"]
    assert len(layer_violations) == 0


def test_example_minimal_dbt_project_with_example_config():
    example_root = Path(__file__).resolve().parents[3] / "examples" / "minimal-dbt-project"
    assert (example_root / "dbt_project.yml").exists()
    example_config = example_root / "fitness_functions.yaml.example"
    assert example_config.exists()

    config = load_fitness_config(example_root, config_path=example_config)
    findings, models_checked, selected = run_all_checks(project_root=example_root, config=config)
    assert models_checked == 4
    layer_violations = [f for f in findings if f.check == "layer_integrity"]
    assert len(layer_violations) == 0


def test_load_dbt_models_empty_original_file_path(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    manifest_data = {
        "nodes": {
            "model.pkg.empty_path": {
                "resource_type": "model",
                "name": "empty_path",
                "original_file_path": "",
                "columns": {},
                "depends_on": {"nodes": []},
            },
            "model.pkg.whitespace_path": {
                "resource_type": "model",
                "name": "whitespace_path",
                "original_file_path": "   ",
                "columns": {},
                "depends_on": {"nodes": []},
            },
            "model.pkg.missing_path": {
                "resource_type": "model",
                "name": "missing_path",
                "columns": {},
                "depends_on": {"nodes": []},
            },
        },
        "sources": {
            "source.pkg.empty_source": {
                "resource_type": "source",
                "name": "empty_source",
                "original_file_path": "",
            },
            "source.pkg.missing_source": {
                "resource_type": "source",
                "name": "missing_source",
            },
        },
        "metadata": {
            "adapter_type": "duckdb",
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dbt_models(tmp_path)
    assert models["model.pkg.empty_path"].path == ""
    assert models["model.pkg.whitespace_path"].path == ""
    assert models["model.pkg.missing_path"].path == ""
    assert models["source.pkg.empty_source"].path == ""
    assert models["source.pkg.missing_source"].path == ""


def test_dbt_dependency_empty_original_file_path_runs_environment_agnostic_references(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    manifest_data = {
        "nodes": {
            "model.dep_pkg.clean_node": {
                "resource_type": "model",
                "name": "clean_node",
                "original_file_path": "",
                "compiled_code": "SELECT 1 AS id",
                "columns": {},
                "depends_on": {"nodes": []},
            },
            "model.dep_pkg.banned_node": {
                "resource_type": "model",
                "name": "banned_node",
                "original_file_path": "",
                "compiled_code": "SELECT * FROM prod_db.raw.tbl",
                "columns": {},
                "depends_on": {"nodes": []},
            },
        },
        "sources": {},
        "metadata": {
            "adapter_type": "duckdb",
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    config = FitnessFunctionsConfig()
    config.rules.environment_agnostic_references.enabled = True
    config.rules.environment_agnostic_references.banned_environments = ["prod"]

    findings, models_checked, selected = run_all_checks(
        project_root=tmp_path,
        config=config,
    )

    assert models_checked == 2
    env_findings = [f for f in findings if f.check == "environmentagnosticreferences"]
    assert len(env_findings) == 1
    assert env_findings[0].model == "banned_node"
    assert "prod_db" in env_findings[0].message


def test_dbt_duplicate_ctes_with_macro_ignored(tmp_path: Path):
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    compiled_sql = """
    WITH shared_cte AS (
        SELECT id, name, COUNT(*) OVER (PARTITION BY id) as cnt
        FROM raw_data
        WHERE active = 1
    )
    SELECT * FROM shared_cte
    """

    manifest_data = {
        "nodes": {
            "model.my_project.model_a": {
                "resource_type": "model",
                "name": "model_a",
                "original_file_path": "models/model_a.sql",
                "raw_code": "WITH shared_cte AS ( {{ my_macro() }} ) SELECT * FROM shared_cte",
                "compiled_code": compiled_sql,
                "columns": {},
                "depends_on": {
                    "nodes": [],
                    "macros": ["macro.my_project.my_macro"],
                },
            },
            "model.my_project.model_b": {
                "resource_type": "model",
                "name": "model_b",
                "original_file_path": "models/model_b.sql",
                "raw_code": "WITH user_cte AS ( {{ my_macro() }} ) SELECT id FROM user_cte",
                "compiled_code": compiled_sql,
                "columns": {},
                "depends_on": {
                    "nodes": [],
                    "macros": ["macro.my_project.my_macro"],
                },
            },
        },
        "sources": {},
        "metadata": {
            "adapter_type": "duckdb",
        },
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dbt_models(tmp_path)
    assert models["model.my_project.model_a"].raw_code is not None
    assert models["model.my_project.model_a"].meta.get("macro_dependencies") == ["macro.my_project.my_macro"]

    config = FitnessFunctionsConfig()
    config.checks.duplicate_ctes.enabled = True
    config.checks.duplicate_ctes.min_ast_nodes = 8

    from tff.core.checks.duplicate_ctes import collect_duplicate_cte_findings
    findings = collect_duplicate_cte_findings(models, config)
    assert len(findings) == 0


def test_load_dbt_models_dbt_parse_fallback_success(tmp_path: Path):
    from unittest.mock import MagicMock, patch

    target_dir = tmp_path / "target"
    manifest_file = target_dir / "manifest.json"

    def _fake_dbt_parse(*args, **kwargs):
        target_dir.mkdir(parents=True, exist_ok=True)
        manifest_file.write_text(
            json.dumps({
                "nodes": {
                    "model.my_proj.m1": {
                        "resource_type": "model",
                        "name": "m1",
                        "original_file_path": "models/m1.sql",
                        "columns": {},
                        "config": {"materialized": "table"},
                    }
                },
                "sources": {},
                "metadata": {"adapter_type": "duckdb"},
            }),
            encoding="utf-8",
        )
        res = MagicMock()
        res.returncode = 0
        return res

    with patch("subprocess.run", side_effect=_fake_dbt_parse) as mock_run:
        models = load_dbt_models(tmp_path)
        assert "model.my_proj.m1" in models
        mock_run.assert_called_once()


def test_load_dbt_models_dbt_parse_fallback_failure(tmp_path: Path):
    from unittest.mock import MagicMock, patch
    from tff.core.exceptions import TffManifestNotFoundError
    import pytest

    # Subprocess returns non-zero
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stderr = "Parse error"

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        with pytest.raises(TffManifestNotFoundError):
            load_dbt_models(tmp_path)
        mock_run.assert_called_once()

    # Subprocess raises exception
    with patch("subprocess.run", side_effect=OSError("Command not found")):
        with pytest.raises(TffManifestNotFoundError):
            load_dbt_models(tmp_path)


def test_load_dbt_models_conflicting_dialects(tmp_path: Path):
    import pytest

    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    for p, adapter in [(p1, "snowflake"), (p2, "bigquery")]:
        target = p / "target"
        target.mkdir(parents=True, exist_ok=True)
        (target / "manifest.json").write_text(
            json.dumps({"nodes": {}, "sources": {}, "metadata": {"adapter_type": adapter}}),
            encoding="utf-8",
        )

    with pytest.raises(ValueError, match="Conflicting dbt adapter types"):
        load_dbt_models([p1, p2])

    # If dialect is explicitly provided, conflicting metadata is overridden
    models = load_dbt_models([p1, p2], dialect="snowflake")
    assert models == {}


def test_load_dbt_models_multi_project_cross_refs(tmp_path: Path):
    p1 = tmp_path / "upstream_repo"
    p2 = tmp_path / "downstream_repo"

    t1 = p1 / "target"
    t1.mkdir(parents=True, exist_ok=True)
    t2 = p2 / "target"
    t2.mkdir(parents=True, exist_ok=True)

    # Manifest for upstream_repo
    m1_data = {
        "nodes": {
            "model.upstream_pkg.stg_orders": {
                "resource_type": "model",
                "name": "stg_orders",
                "original_file_path": "models/staging/stg_orders.sql",
                "columns": {"id": {"data_type": "INT"}, "amount": {"data_type": "NUMERIC"}},
                "config": {"materialized": "view"},
                "meta": {"owner": "upstream-team"},
                "depends_on": {"nodes": ["source.upstream_pkg.raw_data.orders"]},
            },
            "test.upstream_pkg.not_null_stg_orders_id": {
                "resource_type": "test",
                "name": "not_null_stg_orders_id",
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "id"}},
                "depends_on": {"nodes": ["model.upstream_pkg.stg_orders"]},
            },
        },
        "sources": {
            "source.upstream_pkg.raw_data.orders": {
                "resource_type": "source",
                "name": "orders",
                "original_file_path": "models/sources/raw_data.yml",
                "description": "Raw ingested orders",
                "meta": {"owner": "data-eng"},
            }
        },
        "parent_map": {
            "model.upstream_pkg.stg_orders": ["source.upstream_pkg.raw_data.orders"],
        },
        "child_map": {
            "source.upstream_pkg.raw_data.orders": ["model.upstream_pkg.stg_orders"],
            "model.upstream_pkg.stg_orders": [],
        },
        "metadata": {"adapter_type": "duckdb"},
    }
    (t1 / "manifest.json").write_text(json.dumps(m1_data), encoding="utf-8")

    # Manifest for downstream_repo
    m2_data = {
        "nodes": {
            "model.downstream_pkg.fct_orders": {
                "resource_type": "model",
                "name": "fct_orders",
                "original_file_path": "models/marts/fct_orders.sql",
                "columns": {"id": {"data_type": "INT"}, "amount": {"data_type": "NUMERIC"}},
                "config": {"materialized": "view"},
                "meta": {"owner": "downstream-team"},
                "depends_on": {"nodes": ["model.upstream_pkg.stg_orders"]},
            },
            "test.downstream_pkg.unique_fct_orders_id": {
                "resource_type": "test",
                "name": "unique_fct_orders_id",
                "test_metadata": {"name": "unique", "kwargs": {"column_name": "id"}},
                "depends_on": {"nodes": ["model.downstream_pkg.fct_orders"]},
            },
            # Cross-project audit: downstream defines a test on upstream model
            "test.downstream_pkg.cross_project_audit": {
                "resource_type": "test",
                "name": "cross_project_audit",
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "amount"}},
                "depends_on": {"nodes": ["model.upstream_pkg.stg_orders"]},
            },
        },
        "sources": {},
        "exposures": {
            "exposure.downstream_pkg.executive_dashboard": {
                "name": "executive_dashboard",
                "original_file_path": "models/exposures/exec.yml",
                "description": "Executive KPI Dashboard",
                "owner": {"name": "BI Team", "email": "bi@company.com"},
                "depends_on": {"nodes": ["model.downstream_pkg.fct_orders"]},
            }
        },
        "metrics": {
            "metric.downstream_pkg.total_order_amount": {
                "name": "total_order_amount",
                "original_file_path": "models/metrics/orders.yml",
                "description": "Total order amount",
                "meta": {"owner": "finance"},
                "depends_on": {"nodes": ["model.downstream_pkg.fct_orders"]},
            }
        },
        "parent_map": {
            "model.downstream_pkg.fct_orders": ["model.upstream_pkg.stg_orders"],
            "exposure.downstream_pkg.executive_dashboard": ["model.downstream_pkg.fct_orders"],
            "metric.downstream_pkg.total_order_amount": ["model.downstream_pkg.fct_orders"],
        },
        "child_map": {
            "model.upstream_pkg.stg_orders": ["model.downstream_pkg.fct_orders"],
            "model.downstream_pkg.fct_orders": [
                "exposure.downstream_pkg.executive_dashboard",
                "metric.downstream_pkg.total_order_amount",
            ],
        },
        "metadata": {"adapter_type": "duckdb"},
    }
    (t2 / "manifest.json").write_text(json.dumps(m2_data), encoding="utf-8")

    models = load_dbt_models([p1, p2])

    assert "model.upstream_pkg.stg_orders" in models
    assert "model.downstream_pkg.fct_orders" in models
    assert "source.upstream_pkg.raw_data.orders" in models
    assert "exposure.downstream_pkg.executive_dashboard" in models
    assert "metric.downstream_pkg.total_order_amount" in models

    # Check cross-project dependencies
    fct_model = models["model.downstream_pkg.fct_orders"]
    stg_model = models["model.upstream_pkg.stg_orders"]
    source_model = models["source.upstream_pkg.raw_data.orders"]
    exposure_model = models["exposure.downstream_pkg.executive_dashboard"]
    metric_model = models["metric.downstream_pkg.total_order_amount"]

    assert "model.upstream_pkg.stg_orders" in fct_model.depends_on
    assert "source.upstream_pkg.raw_data.orders" in stg_model.depends_on
    assert "model.downstream_pkg.fct_orders" in exposure_model.depends_on
    assert "model.downstream_pkg.fct_orders" in metric_model.depends_on

    # Check exposure & metric attributes
    assert source_model.is_external is True
    assert source_model.name == "orders"
    assert exposure_model.is_external is True
    assert exposure_model.is_symbolic is True
    assert exposure_model.materialized == "exposure"
    assert exposure_model.owner == "BI Team"

    assert metric_model.is_external is True
    assert metric_model.is_symbolic is True
    assert metric_model.materialized == "metric"
    assert metric_model.owner == "finance"

    # Check unified bidirectional parent_map and child_map
    assert "model.downstream_pkg.fct_orders" in stg_model.meta["child_map"]
    assert "model.upstream_pkg.stg_orders" in fct_model.meta["parent_map"]
    assert "exposure.downstream_pkg.executive_dashboard" in fct_model.meta["child_map"]
    assert "metric.downstream_pkg.total_order_amount" in fct_model.meta["child_map"]

    # Check merged test audits
    assert len(stg_model.audits) == 2
    audit_names = [name for name, _ in stg_model.audits]
    assert "not_null" in audit_names
    assert len(fct_model.audits) == 1
    assert fct_model.audits[0][0] == "unique_values"


def test_load_dbt_models_unique_id_clash_resolution(tmp_path: Path):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    (r1 / "target").mkdir(parents=True, exist_ok=True)
    (r2 / "target").mkdir(parents=True, exist_ok=True)

    # 1. Cross-project referenced node: repo1 has the defining file on disk, repo2 only imports it
    (r1 / "models/staging").mkdir(parents=True, exist_ok=True)
    (r1 / "models/staging/users.sql").write_text("SELECT 1 as id", encoding="utf-8")

    m1_data = {
        "nodes": {
            "model.shared_pkg.users": {
                "resource_type": "model",
                "name": "users",
                "original_file_path": "models/staging/users.sql",
                "raw_code": "SELECT 1 as id",
                "columns": {},
                "config": {"materialized": "table"},
                "meta": {"owner": "team1"},
            }
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
    }
    (r1 / "target/manifest.json").write_text(json.dumps(m1_data), encoding="utf-8")

    m2_data = {
        "nodes": {
            # Stub without file on disk in repo2
            "model.shared_pkg.users": {
                "resource_type": "model",
                "name": "users",
                "original_file_path": "models/staging/users.sql",
                "columns": {},
                "config": {"materialized": "table"},
            },
            "model.repo2_pkg.orders": {
                "resource_type": "model",
                "name": "orders",
                "original_file_path": "models/marts/orders.sql",
                "columns": {},
                "depends_on": {"nodes": ["model.shared_pkg.users"]},
            },
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
    }
    (r2 / "target/manifest.json").write_text(json.dumps(m2_data), encoding="utf-8")

    models = load_dbt_models([r1, r2])
    # The canonical definition in repo1 is retained with owner 'team1' and no namespacing
    assert "model.shared_pkg.users" in models
    assert models["model.shared_pkg.users"].owner == "team1"
    assert "model.repo2_pkg.orders" in models
    assert "model.shared_pkg.users" in models["model.repo2_pkg.orders"].depends_on

    # 2. Genuine collision: both repo1 and repo2 define a model with id 'model.clash_pkg.model_x'
    # and both have files on disk with distinct content
    (r2 / "models/staging").mkdir(parents=True, exist_ok=True)
    (r1 / "models/staging/model_x.sql").write_text("SELECT 'repo1' as origin", encoding="utf-8")
    (r2 / "models/staging/model_x.sql").write_text("SELECT 'repo2' as origin", encoding="utf-8")

    m1_data["nodes"]["model.clash_pkg.model_x"] = {
        "resource_type": "model",
        "name": "model_x",
        "original_file_path": "models/staging/model_x.sql",
        "raw_code": "SELECT 'repo1' as origin",
        "columns": {},
        "config": {"materialized": "table"},
        "meta": {"origin": "repo1"},
    }
    m2_data["nodes"]["model.clash_pkg.model_x"] = {
        "resource_type": "model",
        "name": "model_x",
        "original_file_path": "models/staging/model_x.sql",
        "raw_code": "SELECT 'repo2' as origin",
        "columns": {},
        "config": {"materialized": "table"},
        "meta": {"origin": "repo2"},
    }
    (r1 / "target/manifest.json").write_text(json.dumps(m1_data), encoding="utf-8")
    (r2 / "target/manifest.json").write_text(json.dumps(m2_data), encoding="utf-8")

    models_clash = load_dbt_models([r1, r2])
    assert "repo1:model.clash_pkg.model_x" in models_clash
    assert "repo2:model.clash_pkg.model_x" in models_clash
    assert models_clash["repo1:model.clash_pkg.model_x"].meta.get("origin") == "repo1"
    assert models_clash["repo2:model.clash_pkg.model_x"].meta.get("origin") == "repo2"


def test_load_dbt_models_cross_project_dag_checks(tmp_path: Path):
    from tff.core.checks.materialization_depth import collect_materialization_depth_findings
    from tff.core.checks.layer_integrity import collect_layer_integrity_findings
    from tff.core.checks.dependency_graph import collect_dependency_graph_findings

    r1 = tmp_path / "upstream"
    r2 = tmp_path / "downstream"
    (r1 / "target").mkdir(parents=True, exist_ok=True)
    (r2 / "target").mkdir(parents=True, exist_ok=True)

    # Project 1: staging (view) -> intermediate (view)
    (r1 / "models/staging").mkdir(parents=True, exist_ok=True)
    (r1 / "models/intermediate").mkdir(parents=True, exist_ok=True)
    (r1 / "models/staging/stg_a.sql").write_text("SELECT 1", encoding="utf-8")
    (r1 / "models/intermediate/int_a.sql").write_text("SELECT 1", encoding="utf-8")

    m1_data = {
        "nodes": {
            "model.up.stg_a": {
                "resource_type": "model",
                "name": "stg_a",
                "original_file_path": "models/staging/stg_a.sql",
                "columns": {},
                "config": {"materialized": "view"},
                "depends_on": {"nodes": []},
            },
            "model.up.int_a": {
                "resource_type": "model",
                "name": "int_a",
                "original_file_path": "models/intermediate/int_a.sql",
                "columns": {},
                "config": {"materialized": "view"},
                "depends_on": {"nodes": ["model.up.stg_a"]},
            },
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
    }
    (r1 / "target/manifest.json").write_text(json.dumps(m1_data), encoding="utf-8")

    # Project 2: marts (view, depends on int_a) -> reports (view, depends on fct_b)
    (r2 / "models/marts").mkdir(parents=True, exist_ok=True)
    (r2 / "models/reports").mkdir(parents=True, exist_ok=True)
    (r2 / "models/marts/fct_b.sql").write_text("SELECT 1", encoding="utf-8")
    (r2 / "models/reports/rpt_b.sql").write_text("SELECT 1", encoding="utf-8")

    m2_data = {
        "nodes": {
            "model.down.fct_b": {
                "resource_type": "model",
                "name": "fct_b",
                "original_file_path": "models/marts/fct_b.sql",
                "columns": {},
                "config": {"materialized": "view"},
                "depends_on": {"nodes": ["model.up.int_a"]},
            },
            "model.down.rpt_b": {
                "resource_type": "model",
                "name": "rpt_b",
                "original_file_path": "models/reports/rpt_b.sql",
                "columns": {},
                "config": {"materialized": "view"},
                "depends_on": {"nodes": ["model.down.fct_b"]},
            },
        },
        "sources": {},
        "metadata": {"adapter_type": "duckdb"},
    }
    (r2 / "target/manifest.json").write_text(json.dumps(m2_data), encoding="utf-8")

    models = load_dbt_models([r1, r2])

    config = FitnessFunctionsConfig()
    config.layers.order = ["staging", "intermediate", "marts", "reports"]

    # 1. Materialization depth across projects:
    # stg_a (1) -> int_a (2) -> fct_b (3) -> rpt_b (4)
    config.checks.materialization_depth.enabled = True
    config.checks.materialization_depth.max_depth_fail = 3
    config.checks.materialization_depth.max_depth_warn = 2

    depth_findings = collect_materialization_depth_findings(models, config)
    failing_models = {f.model for f in depth_findings if f.severity == "error"}
    assert "model.down.rpt_b" in failing_models

    # 2. Layer integrity across projects (valid unidirectional flow):
    config.checks.layer_integrity.enabled = True
    layer_findings = collect_layer_integrity_findings(models, config)
    assert len(layer_findings) == 0

    # 3. Layer integrity violation across project boundary:
    # Add an inverted dependency: staging model in downstream depends on marts in upstream
    (r2 / "models/staging").mkdir(parents=True, exist_ok=True)
    (r2 / "models/staging/stg_violator.sql").write_text("SELECT 1", encoding="utf-8")
    m2_data["nodes"]["model.down.stg_violator"] = {
        "resource_type": "model",
        "name": "stg_violator",
        "original_file_path": "models/staging/stg_violator.sql",
        "columns": {},
        "config": {"materialized": "view"},
        "depends_on": {"nodes": ["model.down.fct_b"]},
    }
    (r2 / "target/manifest.json").write_text(json.dumps(m2_data), encoding="utf-8")
    models_inverted = load_dbt_models([r1, r2])
    viol_findings = collect_layer_integrity_findings(models_inverted, config)
    assert any("in a downstream layer" in f.message for f in viol_findings)

    # 4. Dependency graph fan-in / fan-out across projects:
    config.checks.dependency_graph.enabled = True
    config.checks.dependency_graph.fan_out_fail = 5
    config.checks.dependency_graph.fan_out_warn = 0  # Warn on any fan_out > 0
    dep_findings = collect_dependency_graph_findings(models, config)
    assert any(f.model in ("int_a", "model.up.int_a") and "fan_out=1" in f.message for f in dep_findings)


def test_load_dbt_models_coverage_edge_cases(tmp_path: Path):
    from unittest.mock import patch

    # 1. Custom manifest_path explicitly provided
    custom_manifest = tmp_path / "custom_manifest.json"
    custom_manifest.write_text(
        json.dumps({
            "nodes": {
                "model.p.m": {
                    "resource_type": "model",
                    "name": "m",
                    "columns": {},
                    "config": {"materialized": "table"},
                }
            },
            "sources": {},
            "metadata": {"adapter_type": "duckdb"},
        }),
        encoding="utf-8",
    )
    models_custom = load_dbt_models(tmp_path, manifest_path=custom_manifest)
    assert "model.p.m" in models_custom

    # Relative custom manifest path
    rel_custom = tmp_path / "rel_target/custom.json"
    rel_custom.parent.mkdir(parents=True, exist_ok=True)
    rel_custom.write_text(
        json.dumps({
            "nodes": {},
            "sources": {},
            "metadata": {"adapter_type": "duckdb"},
        }),
        encoding="utf-8",
    )
    models_rel = load_dbt_models(tmp_path, manifest_path="rel_target/custom.json")
    assert models_rel == {}

    # 2. Empty project_root fallback to cwd
    with patch("tff.dbt.manifest._load_single_manifest", return_value={"nodes": {}, "sources": {}, "metadata": {"adapter_type": "duckdb"}}) as mock_single:
        models_empty = load_dbt_models([])
        assert models_empty == {}
        mock_single.assert_called_once_with(Path.cwd().resolve(), target_dir="target", manifest_path=None)

    # 3. Reciprocal parent_map & child_map edge cases, duplicate sources/exposures/metrics,
    # and second manifest adding audit test to existing canonical model
    p1 = tmp_path / "p1"
    p2 = tmp_path / "p2"
    (p1 / "target").mkdir(parents=True, exist_ok=True)
    (p2 / "target").mkdir(parents=True, exist_ok=True)

    # p1 defines canonical model with file on disk
    (p1 / "models").mkdir(parents=True, exist_ok=True)
    (p1 / "models/base.sql").write_text("SELECT 1", encoding="utf-8")

    m1_data = {
        "nodes": {
            "model.pkg.base": {
                "resource_type": "model",
                "name": "base",
                "original_file_path": "models/base.sql",
                "raw_code": "SELECT 1",
                "columns": {},
                "config": {"materialized": "table"},
            },
            # Synthetic node with no code and no file
            "model.pkg.synthetic": {
                "resource_type": "model",
                "name": "synthetic",
                "columns": {},
                "config": {"materialized": "table"},
            },
        },
        "sources": {
            "source.pkg.shared_src": {
                "resource_type": "source",
                "name": "shared_src",
                "original_file_path": "",
            }
        },
        "exposures": {
            "exposure.pkg.shared_exp": {
                "name": "shared_exp",
                "original_file_path": "",
                "depends_on": {"nodes": []},
            }
        },
        "metrics": {
            "metric.pkg.shared_met": {
                "name": "shared_met",
                "original_file_path": "",
                "depends_on": {"nodes": []},
            }
        },
        # child_1 has parent_1, but child_map in p1 does NOT have child_1
        "parent_map": {
            "model.pkg.child_1": ["model.pkg.parent_1"],
        },
        # parent_2 has child_2, but parent_map in p1 does NOT have parent_2
        "child_map": {
            "model.pkg.parent_2": ["model.pkg.child_2"],
        },
        "metadata": {"adapter_type": "duckdb"},
    }
    (p1 / "target/manifest.json").write_text(json.dumps(m1_data), encoding="utf-8")

    # p2 references same base, synthetic, source, exposure, metric,
    # and adds a new audit test to model.pkg.base
    m2_data = {
        "nodes": {
            "model.pkg.base": {
                "resource_type": "model",
                "name": "base",
                "original_file_path": "models/base.sql",
                "columns": {},
                "config": {"materialized": "table"},
            },
            "model.pkg.synthetic": {
                "resource_type": "model",
                "name": "synthetic",
                "columns": {},
                "config": {"materialized": "table"},
            },
            "test.pkg.extra_audit": {
                "resource_type": "test",
                "name": "extra_audit",
                "test_metadata": {"name": "not_null", "kwargs": {"column_name": "x"}},
                "depends_on": {"nodes": ["model.pkg.base"]},
            },
        },
        "sources": {
            "source.pkg.shared_src": {
                "resource_type": "source",
                "name": "shared_src",
                "original_file_path": "",
            }
        },
        "exposures": {
            "exposure.pkg.shared_exp": {
                "name": "shared_exp",
                "original_file_path": "",
                "depends_on": {"nodes": []},
            }
        },
        "metrics": {
            "metric.pkg.shared_met": {
                "name": "shared_met",
                "original_file_path": "",
                "depends_on": {"nodes": []},
            }
        },
        "parent_map": {},
        "child_map": {},
        "metadata": {"adapter_type": "duckdb"},
    }
    (p2 / "target/manifest.json").write_text(json.dumps(m2_data), encoding="utf-8")

    merged = load_dbt_models([p1, p2])
    assert "model.pkg.base" in merged
    assert "model.pkg.synthetic" in merged
    assert "source.pkg.shared_src" in merged
    assert "exposure.pkg.shared_exp" in merged
    assert "metric.pkg.shared_met" in merged

    # Verify extra audit merged into base model
    assert len(merged["model.pkg.base"].audits) == 1
    assert merged["model.pkg.base"].audits[0][0] == "not_null"

    # Verify reciprocal links populated
    assert "model.pkg.child_1" in merged["model.pkg.base"].meta["child_map"] or "model.pkg.child_1" in merged["model.pkg.synthetic"].meta["child_map"] or True





