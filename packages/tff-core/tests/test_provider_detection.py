"""Unit tests for improved provider auto-detection and SQLMesh false-positive elimination."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from tff.core.adapter import (
    _detect_provider_from_models,
    _detect_provider_single,
    _get_declared_provider,
    _is_sqlmesh_python_config,
    _is_sqlmesh_yaml_config,
    detect_provider,
    is_sqlmesh_project,
)
from tff.core.cli import main
from tff.core.config import FitnessFunctionsConfig, load_fitness_config
from tff.dbt.adapter import DBTAdapter
from tff.sqlmesh.adapter import SQLMeshAdapter


class TestSqlmeshContentInspection:
    """Test content inspection for generic configuration files (config.py, config.yaml, config.yml)."""

    def test_generic_python_config_not_detected_as_sqlmesh(self, tmp_path: Path):
        generic_code = """
import os

DEBUG = True
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///test.db")
PORT = 8080

class Config:
    SECRET_KEY = "supersecret"
"""
        config_py = tmp_path / "config.py"
        config_py.write_text(generic_code)

        assert not _is_sqlmesh_python_config(config_py)
        assert not is_sqlmesh_project(tmp_path)
        with pytest.raises(ValueError, match="Could not detect project type"):
            detect_provider(tmp_path)

    def test_sqlmesh_python_config_with_imports(self, tmp_path: Path):
        sqlmesh_code = """
import sqlmesh
from sqlmesh.core.config import Config, DuckDBConnectionConfig, ModelDefaultsConfig

config = Config(
    model_defaults=ModelDefaultsConfig(dialect="duckdb"),
    gateways={"local": DuckDBConnectionConfig()},
)
"""
        config_py = tmp_path / "config.py"
        config_py.write_text(sqlmesh_code)

        assert _is_sqlmesh_python_config(config_py)
        assert is_sqlmesh_project(tmp_path)
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_sqlmesh_python_config_with_fitness_loader(self, tmp_path: Path):
        code = "from my_custom_loader import FitnessLoader\n"
        config_py = tmp_path / "config.py"
        config_py.write_text(code)

        assert _is_sqlmesh_python_config(config_py)
        assert is_sqlmesh_project(tmp_path)
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_generic_yaml_config_not_detected_as_sqlmesh(self, tmp_path: Path):
        generic_yaml = """
app:
  name: my_app
  port: 8080
database:
  host: localhost
  user: postgres
"""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(generic_yaml)

        assert not _is_sqlmesh_yaml_config(config_yaml)
        assert not is_sqlmesh_project(tmp_path)
        with pytest.raises(ValueError, match="Could not detect project type"):
            detect_provider(tmp_path)

    @pytest.mark.parametrize(
        "key",
        ["gateways", "model_defaults", "default_gateway", "physical_schema"],
    )
    def test_sqlmesh_yaml_config_with_characteristic_keys(self, tmp_path: Path, key: str):
        content = f"{key}:\n  test_val: 123\n"
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(content)

        assert _is_sqlmesh_yaml_config(config_yaml)
        assert is_sqlmesh_project(tmp_path)
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_corrupt_yaml_handled_gracefully(self, tmp_path: Path):
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text("invalid: yaml: [unclosed")
        assert not _is_sqlmesh_yaml_config(config_yaml)
        assert not is_sqlmesh_project(tmp_path)


class TestOfficialSqlmeshConfigNames:
    """Test recognition of official, unambiguous SQLMesh config file names."""

    def test_sqlmesh_yaml_detected(self, tmp_path: Path):
        (tmp_path / "sqlmesh.yaml").touch()
        assert is_sqlmesh_project(tmp_path)
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_sqlmesh_yml_detected(self, tmp_path: Path):
        (tmp_path / "sqlmesh.yml").touch()
        assert is_sqlmesh_project(tmp_path)
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_dot_sqlmesh_dir_detected(self, tmp_path: Path):
        (tmp_path / ".sqlmesh").mkdir()
        assert is_sqlmesh_project(tmp_path)
        assert detect_provider(tmp_path) == "sqlmesh"


class TestAsymmetricConflictWeighting:
    """Test that generic config files alongside dbt_project.yml do not trigger false conflicts."""

    def test_dbt_project_with_generic_config_py_detects_dbt(self, tmp_path: Path):
        (tmp_path / "dbt_project.yml").touch()
        (tmp_path / "config.py").write_text("DEBUG = True\nPORT = 8000\n")

        assert detect_provider(tmp_path) == "dbt"

    def test_dbt_project_with_generic_config_yaml_detects_dbt(self, tmp_path: Path):
        (tmp_path / "dbt_project.yml").touch()
        (tmp_path / "config.yaml").write_text("logging:\n  level: INFO\n")

        assert detect_provider(tmp_path) == "dbt"

    def test_dbt_project_with_real_sqlmesh_config_triggers_conflict(self, tmp_path: Path):
        (tmp_path / "dbt_project.yml").touch()
        (tmp_path / "sqlmesh.yaml").touch()

        with pytest.raises(ValueError, match="Both dbt and SQLMesh configuration files"):
            detect_provider(tmp_path)


class TestModelSyntaxDisambiguation:
    """Test model syntax inspection under models/ as fallback or disambiguation."""

    def test_no_config_files_sqlmesh_models_detected(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "my_model.sql").write_text("""
MODEL (
  name sqlmesh_example.full_model,
  kind FULL,
  cron '@daily'
);

SELECT 1 AS id
""")

        assert _detect_provider_from_models(tmp_path) == "sqlmesh"
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_no_config_files_sqlmesh_python_models_detected(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "my_py_model.py").write_text("""
from sqlmesh.core.model import model

@model("sqlmesh_example.py_model")
def execute(context):
    pass
""")

        assert _detect_provider_from_models(tmp_path) == "sqlmesh"
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_no_config_files_dbt_models_detected(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "orders.sql").write_text("""
{{ config(materialized='table') }}

select id from {{ ref('stg_orders') }}
""")

        assert _detect_provider_from_models(tmp_path) == "dbt"
        assert detect_provider(tmp_path) == "dbt"

    def test_ambiguous_configs_disambiguated_by_sqlmesh_models(self, tmp_path: Path):
        (tmp_path / "dbt_project.yml").touch()
        (tmp_path / "sqlmesh.yaml").touch()
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "model_a.sql").write_text("MODEL (name foo.bar); SELECT 1 AS x")

        assert detect_provider(tmp_path) == "sqlmesh"

    def test_ambiguous_configs_disambiguated_by_dbt_models(self, tmp_path: Path):
        (tmp_path / "dbt_project.yml").touch()
        (tmp_path / "sqlmesh.yaml").touch()
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "model_a.sql").write_text("select * from {{ ref('source_table') }}")

        assert detect_provider(tmp_path) == "dbt"

    def test_adapters_is_applicable_with_models_fallback(self, tmp_path: Path):
        dbt_adapter = DBTAdapter()
        sqlmesh_adapter = SQLMeshAdapter()

        # Initially not applicable
        assert not dbt_adapter.is_applicable(tmp_path)
        assert not sqlmesh_adapter.is_applicable(tmp_path)

        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "model.sql").write_text("MODEL (name foo.bar); SELECT 1")

        assert sqlmesh_adapter.is_applicable(tmp_path)
        assert not dbt_adapter.is_applicable(tmp_path)


class TestDeclarativeProviderConfig:
    """Test declarative provider field in fitness_functions.yaml."""

    def test_fitness_functions_config_provider_field(self):
        cfg = FitnessFunctionsConfig(provider="dbt")
        assert cfg.provider == "dbt"

        cfg_upper = FitnessFunctionsConfig(provider="  SQLMESH  ")
        assert cfg_upper.provider == "sqlmesh"

        cfg_auto = FitnessFunctionsConfig(provider="auto")
        assert cfg_auto.provider is None

    def test_declarative_provider_in_yaml_bypasses_autodetect(self, tmp_path: Path):
        ff_yaml = tmp_path / "fitness_functions.yaml"
        ff_yaml.write_text("provider: sqlmesh\n")

        assert _get_declared_provider(tmp_path) == "sqlmesh"
        assert detect_provider(tmp_path) == "sqlmesh"

    def test_declarative_provider_dbt_in_yaml(self, tmp_path: Path):
        ff_yaml = tmp_path / "fitness_functions.yaml"
        ff_yaml.write_text("provider: dbt\n")

        assert _get_declared_provider(tmp_path) == "dbt"
        assert detect_provider(tmp_path) == "dbt"

    def test_declarative_provider_custom_config_path(self, tmp_path: Path):
        custom_yaml = tmp_path / "custom_config.yaml"
        custom_yaml.write_text("provider: dataform\n")

        assert _get_declared_provider(tmp_path, config_path="custom_config.yaml") == "dataform"
        assert detect_provider(tmp_path, config_path="custom_config.yaml") == "dataform"

    def test_load_fitness_config_reads_declared_provider(self, tmp_path: Path):
        ff_yaml = tmp_path / "fitness_functions.yaml"
        ff_yaml.write_text("provider: sqlmesh\n")

        cfg = load_fitness_config(tmp_path)
        assert cfg.provider == "sqlmesh"

    def test_detect_provider_single_helper(self, tmp_path: Path):
        (tmp_path / "dbt_project.yml").touch()
        assert _detect_provider_single(tmp_path) == "dbt"

    def test_cli_explicit_provider_overrides_declarative_config(self, tmp_path: Path):
        ff_yaml = tmp_path / "fitness_functions.yaml"
        ff_yaml.write_text("provider: sqlmesh\n")

        mock_adapter = MagicMock()
        mock_adapter.provider_name = "dbt"
        mock_adapter.run_checks.return_value = ([], 10, ["dbt"])

        with (
            patch("tff.core.cli._get_adapter", return_value=mock_adapter) as mock_get_adapter,
            patch("tff.core.cli.load_fitness_config", return_value=FitnessFunctionsConfig(provider="sqlmesh")),
            patch("tff.core.cli.render_lint_report", return_value=True),
        ):
            # Pass explicit --provider dbt to override declared sqlmesh
            exit_code = main(["lint", "--project", str(tmp_path), "--provider", "dbt"])
            assert exit_code == 0
            mock_get_adapter.assert_called_once_with("dbt")


class TestProviderDetectionEdgeCases:
    """Test edge cases, OS errors, limits, and branch coverage for provider detection."""

    def test_is_sqlmesh_python_config_os_error(self, tmp_path: Path):
        p = tmp_path / "config.py"
        p.touch()
        with patch.object(Path, "read_text", side_effect=OSError("Read error")):
            assert not _is_sqlmesh_python_config(p)

    def test_is_sqlmesh_python_config_with_dbt_project_matching_terms(self, tmp_path: Path):
        p = tmp_path / "config.py"
        p.write_text("config = Config(gateways={'local': DuckDBConnectionConfig()})")
        assert _is_sqlmesh_python_config(p, has_dbt_project=True)

    def test_is_sqlmesh_python_config_with_dbt_project_generic_config(self, tmp_path: Path):
        p = tmp_path / "config.py"
        p.write_text("config = Config(unrelated_param=123)")
        assert not _is_sqlmesh_python_config(p, has_dbt_project=True)

    def test_is_sqlmesh_python_config_config_call_without_dbt_project(self, tmp_path: Path):
        p = tmp_path / "config.py"
        p.write_text("config = Config(dialect='duckdb')")
        assert _is_sqlmesh_python_config(p, has_dbt_project=False)

    def test_is_sqlmesh_yaml_config_non_dict(self, tmp_path: Path):
        p = tmp_path / "config.yaml"
        p.write_text("- item1\n- item2\n")
        assert not _is_sqlmesh_yaml_config(p)

    def test_detect_provider_from_models_rglob_os_error(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        with patch.object(Path, "rglob", side_effect=OSError("Disk error")):
            assert _detect_provider_from_models(tmp_path) is None

    def test_detect_provider_from_models_skips_non_files(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "subdir.sql").mkdir()
        (models_dir / "real.sql").write_text("MODEL (name x); SELECT 1")
        assert _detect_provider_from_models(tmp_path) == "sqlmesh"

    def test_detect_provider_from_models_max_files_limit(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        for i in range(35):
            (models_dir / f"model_{i:02d}.sql").write_text(f"MODEL (name m{i}); SELECT {i}")
        assert _detect_provider_from_models(tmp_path) == "sqlmesh"

    def test_detect_provider_from_models_file_read_os_error(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "test.sql").write_text("MODEL (name x); SELECT 1")
        with patch.object(Path, "read_text", side_effect=OSError("Read error")):
            assert _detect_provider_from_models(tmp_path) is None

    def test_detect_provider_from_models_ambiguous_returns_none(self, tmp_path: Path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "sqlmesh_model.sql").write_text("MODEL (name x); SELECT 1")
        (models_dir / "dbt_model.sql").write_text("select * from {{ ref('stg') }}")
        assert _detect_provider_from_models(tmp_path) is None

    def test_get_declared_provider_corrupt_yaml(self, tmp_path: Path):
        ff = tmp_path / "fitness_functions.yaml"
        ff.write_text("invalid: yaml: [unclosed")
        assert _get_declared_provider(tmp_path) is None

    def test_fitness_functions_config_provider_validation(self):
        cfg_none = FitnessFunctionsConfig(provider=None)
        assert cfg_none.provider is None

        cfg_empty = FitnessFunctionsConfig(provider="")
        assert cfg_empty.provider is None

        cfg_whitespace = FitnessFunctionsConfig(provider="   ")
        assert cfg_whitespace.provider is None

        with pytest.raises(ValueError, match="Expected string for provider"):
            FitnessFunctionsConfig(provider=123)

    def test_cli_docs_custom_config_path(self, tmp_path: Path):
        (tmp_path / "dbt_project.yml").touch()
        custom_cfg = tmp_path / "custom_fitness.yaml"
        custom_cfg.write_text("provider: dbt\n")
        with (
            patch("tff.core.docs.generate_docs_dashboard", return_value=tmp_path / "out.html"),
            patch("tff.core.cli._detect_provider", return_value="dbt") as mock_det,
        ):
            exit_code = main(["docs", "-p", str(tmp_path), "--config", str(custom_cfg)])
            assert exit_code == 0
            mock_det.assert_called_once_with([tmp_path.resolve()], config_path=str(custom_cfg))
