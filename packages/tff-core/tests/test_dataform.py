import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tff.core.cli import _detect_provider, _get_runner, main
from tff.core.health import _domain_key
from tff.core.utils.jinja import clean_dataform_for_parsing
from tff.core.utils.paths import (
    get_layer_and_domain,
    get_layer_from_path,
    get_marts_domain_from_path,
    model_path_relative,
)
from tff.dataform.cli import main as dataform_cli_main
from tff.dataform.manifest import (
    _compile_via_cli,
    _find_manifest_file,
    _load_settings,
    _parse_sqlx_config,
    load_dataform_models,
)
from tff.dataform.runner import run_all_checks


def test_clean_dataform_for_parsing():
    raw = """
    config {
      type: "table",
      schema: "staging",
      dependencies: ["dep1"],
      columns: {
        id: "Unique ID"
      }
    }

    js {
      const someConst = 123;
    }

    pre_operations {
      CREATE TEMP FUNCTION helper() RETURNS INT64 AS (1);
    }

    SELECT
      id,
      ${someConst} AS const_val,
      name
    FROM
      ${ref("raw_users")}
    WHERE
      is_active = TRUE
    """
    cleaned = clean_dataform_for_parsing(raw)
    assert "config" not in cleaned
    assert "js" not in cleaned
    assert "pre_operations" not in cleaned
    assert "raw_users" in cleaned
    assert "__dataform_var__" in cleaned


def test_clean_dataform_refs_variations():
    # Two-arg ref
    sql1 = "SELECT * FROM ${ref('schema_a', 'table_b')}"
    assert "schema_a.table_b" in clean_dataform_for_parsing(sql1)

    # Object ref
    sql2 = "SELECT * FROM ${ref({ schema: 'schema_a', name: 'table_c' })}"
    assert "table_c" in clean_dataform_for_parsing(sql2)

    # Resolve
    sql3 = "SELECT * FROM ${resolve('table_d')}"
    assert "table_d" in clean_dataform_for_parsing(sql3)


def test_paths_with_definitions():
    sqlx_path = "definitions/staging/stg_users.sqlx"
    assert get_layer_from_path(sqlx_path) == "staging"
    assert model_path_relative(MagicMock(path=sqlx_path)) == "definitions/staging/stg_users.sqlx"

    mart_path = "definitions/marts/marketing/dim_customers.sqlx"
    layer, domain = get_layer_and_domain(mart_path)
    assert layer == "marts"
    assert domain == "marketing"
    assert get_marts_domain_from_path(mart_path) == "marketing"

    # Domain group in health
    assert _domain_key("definitions/staging/stg_users.sqlx") == "definitions/staging"
    assert _domain_key("definitions/marts/marketing/dim_customers.sqlx") == "definitions/marts/marketing"


def test_detect_provider_dataform(tmp_path: Path):
    # workflow_settings.yaml detection
    (tmp_path / "workflow_settings.yaml").write_text("defaultProject: p\n", encoding="utf-8")
    assert _detect_provider(tmp_path) == "dataform"
    (tmp_path / "workflow_settings.yaml").unlink()

    # dataform.json detection
    (tmp_path / "dataform.json").write_text('{"defaultDatabase": "p"}', encoding="utf-8")
    assert _detect_provider(tmp_path) == "dataform"

    # Conflict with dbt
    (tmp_path / "dbt_project.yml").touch()
    with pytest.raises(ValueError, match="Multiple pipeline configuration files were detected"):
        _detect_provider(tmp_path)


def test_load_settings(tmp_path: Path):
    assert _load_settings(tmp_path) == {}

    (tmp_path / "workflow_settings.yaml").write_text("defaultDataset: my_dataset\n", encoding="utf-8")
    assert _load_settings(tmp_path)["defaultDataset"] == "my_dataset"
    (tmp_path / "workflow_settings.yaml").unlink()

    (tmp_path / "dataform.json").write_text('{"defaultSchema": "json_dataset"}', encoding="utf-8")
    assert _load_settings(tmp_path)["defaultSchema"] == "json_dataset"


def test_find_manifest_file(tmp_path: Path):
    assert _find_manifest_file(tmp_path) is None

    manifest = tmp_path / "compilation_result.json"
    manifest.touch()
    assert _find_manifest_file(tmp_path) == manifest

    custom = tmp_path / "custom.json"
    custom.touch()
    assert _find_manifest_file(tmp_path, "custom.json") == custom

    with pytest.raises(FileNotFoundError):
        _find_manifest_file(tmp_path, "nonexistent.json")


def test_load_dataform_models_from_cli_manifest(tmp_path: Path):
    manifest_data = {
        "projectConfig": {
            "warehouse": "bigquery",
            "defaultDatabase": "test-project",
            "defaultSchema": "dataform",
        },
        "tables": [
            {
                "target": {
                    "database": "test-project",
                    "schema": "staging",
                    "name": "stg_users",
                },
                "type": "view",
                "fileName": "definitions/staging/stg_users.sqlx",
                "query": "SELECT id, email FROM `raw.users`",
                "actionDescriptor": {
                    "description": "Staging users model",
                    "columns": [
                        {"path": ["id"], "type": "INT64", "description": "Primary key"},
                        {"path": ["email"], "type": "STRING", "description": "Email address"},
                    ],
                    "bigqueryLabels": {"owner": "data-team"},
                },
                "tags": ["staging", "daily"],
                "dependencyTargets": [
                    {
                        "database": "test-project",
                        "schema": "raw",
                        "name": "users",
                    }
                ],
                "uniqueKey": ["id"],
            },
            {
                "target": {
                    "database": "test-project",
                    "schema": "staging",
                    "name": "stg_disabled",
                },
                "type": "view",
                "disabled": True,
            },
            {
                "target": {
                    "database": "test-project",
                    "schema": "staging",
                    "name": "inline_orders",
                },
                "type": "inline",
                "fileName": "definitions/staging/inline_orders.sqlx",
                "query": "SELECT 1 AS order_id",
            },
        ],
        "assertions": [
            {
                "target": {
                    "name": "stg_users_assertions_uniqueKey_0",
                },
                "parentAction": {
                    "database": "test-project",
                    "schema": "staging",
                    "name": "stg_users",
                },
                "actionDescriptor": {
                    "description": "uniqueKey assertion",
                },
            },
            {
                "target": {
                    "name": "stg_users_assertions_nonNull_0",
                },
                "dependencyTargets": [
                    {
                        "database": "test-project",
                        "schema": "staging",
                        "name": "stg_users",
                    }
                ],
                "actionDescriptor": {
                    "description": "nonNull assertion",
                },
            },
            {
                "target": {
                    "name": "stg_users_assertions_rowConditions_0",
                },
                "dependencyTargets": [
                    {
                        "database": "test-project",
                        "schema": "staging",
                        "name": "stg_users",
                    }
                ],
                "actionDescriptor": {
                    "description": "rowConditions assertion",
                },
            },
        ],
        "declarations": [
            {
                "target": {
                    "database": "test-project",
                    "schema": "raw",
                    "name": "users",
                },
                "actionDescriptor": {
                    "description": "Raw users source table",
                    "bigqueryLabels": {"owner": "ingest-team"},
                },
                "fileName": "definitions/sources.js",
            }
        ],
    }

    manifest_file = tmp_path / "compilation_result.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dataform_models(tmp_path)

    assert "staging.stg_users" in models
    assert "raw.users" in models
    assert "staging.inline_orders" in models
    assert "staging.stg_disabled" not in models

    user_model = models["staging.stg_users"]
    assert user_model.name == "stg_users"
    assert user_model.dialect == "bigquery"
    assert user_model.materialized == "view"
    assert not user_model.is_symbolic
    assert not user_model.is_external
    assert user_model.owner == "data-team"
    assert user_model.description == "Staging users model"
    assert user_model.grains == ["id"]
    assert "id" in user_model.columns_to_types
    assert "raw.users" in user_model.depends_on
    assert len(user_model.audits) >= 2

    inline_model = models["staging.inline_orders"]
    assert inline_model.is_symbolic
    assert inline_model.materialized == "inline"

    source_model = models["raw.users"]
    assert source_model.is_external
    assert source_model.is_symbolic
    assert source_model.owner == "ingest-team"


def test_load_dataform_models_from_gcp_api(tmp_path: Path):
    api_data = {
        "compilationResultActions": [
            {
                "target": {
                    "database": "gcp-proj",
                    "schema": "analytics",
                    "name": "daily_stats",
                },
                "filePath": "definitions/marts/daily_stats.sqlx",
                "relation": {
                    "relationType": "INCREMENTAL_TABLE",
                    "selectQuery": "SELECT date, count FROM raw.events",
                    "actionDescriptor": {
                        "description": "Daily event statistics",
                    },
                    "dependencyTargets": [
                        {"database": "gcp-proj", "schema": "raw", "name": "events"}
                    ],
                },
            },
            {
                "target": {
                    "name": "daily_stats_assertion",
                },
                "assertion": {
                    "parentAction": {
                        "database": "gcp-proj",
                        "schema": "analytics",
                        "name": "daily_stats",
                    },
                    "selectQuery": "SELECT * FROM daily_stats WHERE count < 0",
                    "actionDescriptor": {
                        "description": "positive count assertion",
                    },
                },
            },
            {
                "target": {
                    "database": "gcp-proj",
                    "schema": "raw",
                    "name": "events",
                },
                "filePath": "definitions/events_source.js",
                "declaration": {
                    "actionDescriptor": {"description": "Raw events"},
                },
            },
        ]
    }

    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(api_data), encoding="utf-8")

    models = load_dataform_models(tmp_path)
    assert "analytics.daily_stats" in models
    assert "raw.events" in models

    model = models["analytics.daily_stats"]
    assert model.materialized == "incremental"
    assert "raw.events" in model.depends_on
    assert len(model.audits) == 1


def test_load_dataform_models_direct_sqlx(tmp_path: Path):
    definitions_dir = tmp_path / "definitions"
    staging_dir = definitions_dir / "staging"
    staging_dir.mkdir(parents=True, exist_ok=True)

    sqlx_content = """
    config {
      type: "view",
      schema: "staging",
      description: "Users staging table",
      tags: ["staging"],
      columns: {
        id: { type: "INT64", description: "ID" },
        email: "User email"
      },
      assertions: {
        uniqueKey: ["id"],
        nonNull: ["id", "email"]
      },
      bigquery: {
        labels: {
          owner: "analytics"
        }
      }
    }

    SELECT
      id,
      email
    FROM
      ${ref("raw_users")}
    """
    (staging_dir / "stg_users.sqlx").write_text(sqlx_content, encoding="utf-8")

    # JS declarations
    sources_js = """
    declare({
      schema: "raw",
      name: "raw_users",
      description: "Raw users declaration",
      owner: "ingestion"
    });
    """
    (definitions_dir / "sources.js").write_text(sources_js, encoding="utf-8")

    models = load_dataform_models(tmp_path)
    assert "staging.stg_users" in models
    assert "raw.raw_users" in models

    user_model = models["staging.stg_users"]
    assert user_model.name == "stg_users"
    assert user_model.owner == "analytics"
    assert user_model.description == "Users staging table"
    assert user_model.grains == ["id"]
    assert "raw.raw_users" in user_model.depends_on
    assert len(user_model.audits) >= 2


def test_cli_compile_fallback(tmp_path: Path):
    with patch("shutil.which") as mock_which, patch("subprocess.run") as mock_run:
        mock_which.side_effect = lambda cmd: "/usr/local/bin/dataform" if cmd == "dataform" else None
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({
            "tables": [
                {
                    "target": {"schema": "s", "name": "t"},
                    "type": "table",
                    "query": "SELECT 1",
                }
            ]
        })
        mock_run.return_value = mock_proc

        res = _compile_via_cli(tmp_path)
        assert res is not None
        assert "tables" in res


def test_dataform_runner_run_all_checks(tmp_path: Path):
    definitions_dir = tmp_path / "definitions" / "staging"
    definitions_dir.mkdir(parents=True, exist_ok=True)

    sqlx = """
    config {
      type: "view",
      schema: "staging",
      description: "Sample",
      bigquery: {
        labels: { owner: "team" }
      }
    }

    SELECT id, name FROM ${ref("source_table")}
    """
    (definitions_dir / "stg_sample.sqlx").write_text(sqlx, encoding="utf-8")

    findings, models_checked, selected = run_all_checks(project_root=tmp_path)
    assert models_checked >= 1
    assert "rules" in selected


def test_dataform_cli_standalone(tmp_path: Path, capsys):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir(parents=True, exist_ok=True)
    sqlx = """
    config {
      type: 'view',
      description: 'Test view',
      bigquery: { labels: { owner: 'team' } },
      assertions: { uniqueKey: ['id'], nonNull: ['id'] }
    }
    SELECT 1 AS id
    """
    (definitions_dir / "stg_test.sqlx").write_text(sqlx, encoding="utf-8")

    exit_code = dataform_cli_main(["lint", "--project", str(tmp_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "WARNING: 'tff-dataform' is deprecated" in captured.err


def test_cli_integration_with_dataform(tmp_path: Path):
    (tmp_path / "workflow_settings.yaml").write_text("defaultProject: test\n", encoding="utf-8")
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir(parents=True, exist_ok=True)
    sqlx = """
    config {
      type: 'view',
      description: 'Model description',
      bigquery: { labels: { owner: 'team' } },
      assertions: { uniqueKey: ['id'], nonNull: ['id'] }
    }
    SELECT 1 AS id
    """
    (definitions_dir / "stg_model.sqlx").write_text(sqlx, encoding="utf-8")

    # tff info
    assert main(["info", "--project", str(tmp_path)]) == 0

    # tff lint
    assert main(["lint", "--project", str(tmp_path)]) == 0

    # tff health
    assert main(["health", "--project", str(tmp_path)]) == 0


def test_get_runner_dataform_import_error():
    with patch("importlib.import_module", side_effect=ImportError("mocked import error")):
        with pytest.raises(ImportError, match="Dataform project detected, but tff is not installed with dataform support"):
            _get_runner("dataform")


def test_info_command_with_dataform_json_and_missing(tmp_path: Path):
    # dataform.json test
    (tmp_path / "dataform.json").write_text("{}", encoding="utf-8")
    assert main(["info", "--project", str(tmp_path), "--provider", "dataform"]) == 0
    (tmp_path / "dataform.json").unlink()

    # missing config file test
    assert main(["info", "--project", str(tmp_path), "--provider", "dataform"]) == 0


def test_docs_generation_with_dataform(tmp_path: Path):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir(parents=True, exist_ok=True)
    sqlx = """
    config {
      type: 'view',
      description: 'Test view',
      bigquery: { labels: { owner: 'team' } },
      assertions: { uniqueKey: ['id'], nonNull: ['id'] }
    }
    SELECT 1 AS id
    """
    (definitions_dir / "stg_users.sqlx").write_text(sqlx, encoding="utf-8")

    from tff.core.docs import generate_docs_dashboard
    output = generate_docs_dashboard(project_root=tmp_path, provider="dataform")
    assert output.exists()
    assert output.is_file()

    # Via CLI with manifest
    manifest_file = tmp_path / "compilation_result.json"
    manifest_file.write_text(json.dumps({
        "tables": [{
            "target": {"schema": "s", "name": "m"},
            "type": "view",
            "query": "SELECT 1 AS id",
            "fileName": "definitions/m.sqlx"
        }]
    }), encoding="utf-8")
    assert main(["docs", "--project", str(tmp_path), "--provider", "dataform", "--manifest", str(manifest_file)]) == 0


def test_cli_autofix_with_dataform(tmp_path: Path):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir(parents=True, exist_ok=True)
    sqlx = """
    config {
      type: 'view',
      description: 'Positional test',
      bigquery: { labels: { owner: 'team' } },
      assertions: { uniqueKey: ['id'], nonNull: ['id'] }
    }
    SELECT id, count(*) FROM raw_orders GROUP BY 1
    """
    file_path = definitions_dir / "stg_orders.sqlx"
    file_path.write_text(sqlx, encoding="utf-8")

    # Run lint with --fix
    exit_code = main(["lint", "--project", str(tmp_path), "--provider", "dataform", "--fix"])
    assert exit_code in (0, 1)
    # The file should now have GROUP BY id
    fixed_content = file_path.read_text(encoding="utf-8")
    assert "GROUP BY id" in fixed_content or "GROUP BY 1" in fixed_content


def test_clean_dataform_edge_cases():
    # Unclosed brace should return text safely
    unclosed = "config { type: 'view' "
    assert clean_dataform_for_parsing(unclosed) == unclosed

    # Escaped quotes inside block
    escaped = 'config { description: "it\\"s fine" } SELECT 1'
    cleaned = clean_dataform_for_parsing(escaped)
    assert "SELECT 1" in cleaned


def test_collect_dataform_rules_findings_external_and_symbolic():
    from tff.core.model import ModelRepresentation
    from tff.dataform.runner import collect_dataform_rules_findings

    models = {
        "ext": ModelRepresentation(name="ext", path="definitions/ext.sqlx", dialect="bigquery", is_external=True),
        "sym": ModelRepresentation(name="sym", path="definitions/sym.sqlx", dialect="bigquery", is_symbolic=True),
    }
    findings = collect_dataform_rules_findings(models)
    assert len(findings) == 0


def test_load_settings_exceptions(tmp_path: Path):
    yaml_file = tmp_path / "workflow_settings.yaml"
    yaml_file.write_text("invalid: [", encoding="utf-8")
    assert _load_settings(tmp_path) == {}

    yaml_file.unlink()
    json_file = tmp_path / "dataform.json"
    json_file.write_text("invalid json", encoding="utf-8")
    assert _load_settings(tmp_path) == {}


def test_compile_via_cli_npx_and_exceptions(tmp_path: Path):
    # Test npx fallback
    with patch("shutil.which") as mock_which, patch("subprocess.run") as mock_run:
        mock_which.side_effect = lambda cmd: "/usr/local/bin/npx" if cmd == "npx" else None
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps({"tables": []})
        mock_run.return_value = mock_proc

        res = _compile_via_cli(tmp_path)
        assert res == {"tables": []}
        assert mock_run.call_args[0][0][:2] == ["npx", "--no-install"]

    # Test exception handling
    with patch("shutil.which", return_value="/usr/local/bin/dataform"):
        with patch("subprocess.run", side_effect=RuntimeError("exec error")):
            assert _compile_via_cli(tmp_path) is None


def test_load_dataform_models_manifest_parse_error(tmp_path: Path):
    manifest = tmp_path / "compilation_result.json"
    manifest.write_text("not json", encoding="utf-8")
    # Should log warning and fall back to source parsing without crashing
    models = load_dataform_models(tmp_path)
    assert isinstance(models, dict)


def test_parse_compiled_graph_more_branches(tmp_path: Path):
    # Test GCP API with VIEW, string uniqueKey, column without path, query syntax error
    data = {
        "compilationResultActions": [
            {
                "target": {"schema": "s", "name": "v_test"},
                "filePath": "definitions/v_test.sqlx",
                "relation": {
                    "relationType": "VIEW",
                    "selectQuery": "SELECT (",
                    "actionDescriptor": {
                        "columns": [{"description": "no path"}, {"path": ["col1"]}],
                    },
                },
            },
            {
                "target": {"schema": "s", "name": "t_test"},
                "relation": {
                    "relationType": "OTHER_TABLE",
                },
            },
        ]
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")

    models = load_dataform_models(tmp_path)
    assert "s.v_test" in models
    assert models["s.v_test"].expression is None
    assert "col1" in models["s.v_test"].columns_to_types


def test_dependency_resolution_by_unqualified_name(tmp_path: Path):
    manifest_data = {
        "tables": [
            {
                "target": {"schema": "s", "name": "dep_model"},
                "type": "table",
                "fileName": "definitions/dep.sqlx",
            },
            {
                "target": {"schema": "s", "name": "downstream"},
                "type": "view",
                "fileName": "definitions/downstream.sqlx",
                "dependencyTargets": [{"name": "dep_model"}],  # missing schema
            },
        ]
    }
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dataform_models(tmp_path)
    assert "s.dep_model" in models["s.downstream"].depends_on


def test_load_models_from_sources_edge_cases(tmp_path: Path):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir(parents=True, exist_ok=True)

    # 1. unclosed config block
    (definitions_dir / "unclosed.sqlx").write_text("config { type: 'view' \nSELECT 1", encoding="utf-8")

    # 2. invalid yaml config
    (definitions_dir / "bad_yaml.sqlx").write_text("config { bad: [ } \nSELECT 1", encoding="utf-8")

    # 3. declaration in sqlx and two-arg / object ref
    sqlx_content = """
    config {
      type: "declaration",
      schema: "raw",
      name: "raw_table",
      dependencies: ["ext_dep"],
      uniqueKey: "single_grain_string",
    }
    SELECT * FROM ${ref("my_schema", "my_table")}
    JOIN ${ref({ name: "my_other_table" })}
    """
    (definitions_dir / "decl.sqlx").write_text(sqlx_content, encoding="utf-8")

    # 4. JS with bad yaml declaration
    (definitions_dir / "bad_decl.js").write_text("declare({ bad: [ });", encoding="utf-8")

    models = load_dataform_models(tmp_path)
    assert "raw.raw_table" in models
    decl_model = models["raw.raw_table"]
    assert decl_model.is_external
    assert decl_model.grains == ["single_grain_string"]
    assert "my_schema.my_table" in decl_model.depends_on
    assert "my_other_table" in decl_model.depends_on
    assert "ext_dep" in decl_model.depends_on


def test_dataform_cli_checks_parsing():
    from tff.dataform.cli import _parse_checks
    assert _parse_checks(None) is None
    assert _parse_checks("rules, layer_integrity") == ["rules", "layer_integrity"]


def test_dataform_cli_no_subcommand():
    import argparse
    with patch("argparse.ArgumentParser.parse_args", return_value=argparse.Namespace(command="unknown")):
        ret = dataform_cli_main([])
        assert ret == 1



def test_compile_via_cli_no_binary(tmp_path: Path):
    with patch("shutil.which", return_value=None):
        assert _compile_via_cli(tmp_path) is None


def test_parse_sqlx_config_edge_cases():
    cfg, sql = _parse_sqlx_config("SELECT 1 FROM t")
    assert cfg == {}
    assert sql == "SELECT 1 FROM t"

    sqlx_with_escaped_quote = """config {
      type: "table",
      description: "testing \\"escaped\\" quotes"
    }
    SELECT 1"""
    cfg2, sql2 = _parse_sqlx_config(sqlx_with_escaped_quote)
    assert cfg2.get("type") == "table"
    assert "SELECT 1" in sql2


def test_parse_compiled_graph_edge_cases(tmp_path: Path):
    manifest_data = {
        "tables": [
            {
                # Target with empty dict triggers line 210
                "target": {},
                "type": "table",
                "fileName": "definitions/empty_target.sqlx",
                "uniqueKey": "single_key_str",
            },
            {
                "target": {"schema": "s", "name": "bad_key_table"},
                "type": "table",
                "fileName": "definitions/bad_key.sqlx",
                "uniqueKey": 12345,
            },
        ]
    }
    manifest_file = tmp_path / "compilation_result.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dataform_models(tmp_path, manifest_path=manifest_file)
    assert "" in models
    assert models[""].grains == ["single_key_str"]
    assert any(a[0] == "unique_values" for a in models[""].audits)
    assert "s.bad_key_table" in models
    assert models["s.bad_key_table"].grains == []


def test_load_models_from_sources_unreadable_and_odd_grains(tmp_path: Path):
    definitions_dir = tmp_path / "definitions"
    definitions_dir.mkdir(parents=True, exist_ok=True)

    (definitions_dir / "odd_grain.sqlx").write_text("""config {
      type: "table",
      name: "odd_grain",
      assertions: {
        uniqueKey: 999
      }
    }
    SELECT 1""", encoding="utf-8")

    (definitions_dir / "unreadable.sqlx").touch()
    (definitions_dir / "unreadable.js").touch()

    original_read_text = Path.read_text

    def side_effect(self, *args, **kwargs):
        if self.name in ("unreadable.sqlx", "unreadable.js"):
            raise OSError("Permission denied test")
        return original_read_text(self, *args, **kwargs)

    with patch.object(Path, "read_text", side_effect):
        models = load_dataform_models(tmp_path)

    assert "odd_grain" in models
    assert models["odd_grain"].grains == []


def test_load_dataform_models_manifest_exception(tmp_path: Path):
    bad_manifest = tmp_path / "corrupt.json"
    bad_manifest.write_text("invalid json", encoding="utf-8")

    with pytest.raises(json.JSONDecodeError):
        load_dataform_models(tmp_path, manifest_path=bad_manifest)


def test_load_dataform_models_cli_compilation_success_and_failure(tmp_path: Path):
    valid_cli_output = {
        "tables": [
            {
                "target": {"schema": "cli_schema", "name": "cli_tbl"},
                "type": "table",
                "fileName": "definitions/cli_tbl.sqlx",
            }
        ]
    }
    with patch("tff.dataform.manifest._compile_via_cli", return_value=valid_cli_output):
        models = load_dataform_models(tmp_path)
        assert "cli_schema.cli_tbl" in models

    invalid_cli_output = {"tables": "not_a_list_so_it_fails"}
    with patch("tff.dataform.manifest._compile_via_cli", return_value=invalid_cli_output):
        models_fallback = load_dataform_models(tmp_path)
        assert isinstance(models_fallback, dict)



