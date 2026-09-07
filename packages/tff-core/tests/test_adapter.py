"""Unit tests for PipelineAdapter interface, registries, and concrete adapters."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from tff.core.adapter import (
    PipelineAdapter,
    detect_provider,
    get_adapter,
)
from tff.core.cli import _MockRunnerAdapter, _get_adapter, main
from tff.core.config import FitnessFunctionsConfig
from tff.dataform.adapter import DataformAdapter
from tff.dbt.adapter import DBTAdapter
from tff.sqlmesh.adapter import SQLMeshAdapter


class ConcreteDummyAdapter(PipelineAdapter):
    @property
    def provider_name(self) -> str:
        return "dummy"

    def is_applicable(self, project_root: Path) -> bool:
        return True

    def load_models(
        self,
        project_root: Path,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ):
        return {}

    def run_checks(
        self,
        project_root: Path,
        config,
        checks=None,
        dialect=None,
        manifest_path=None,
        models=None,
    ):
        return [], 0, []


def test_pipeline_adapter_base_defaults():
    adapter = ConcreteDummyAdapter()
    assert adapter.provider_name == "dummy"
    assert adapter.is_applicable(Path.cwd()) is True
    assert adapter.load_models(Path.cwd()) == {}
    assert adapter.run_checks(Path.cwd(), MagicMock()) == ([], 0, [])
    assert (
        adapter.apply_metadata_fix(Path.cwd(), Path("foo.sql"), "foo", True, True)
        is None
    )
    assert adapter.get_diagnostic_files(Path.cwd()) == []


def test_get_adapter_instances():
    assert isinstance(get_adapter("dbt"), DBTAdapter)
    assert isinstance(get_adapter("sqlmesh"), SQLMeshAdapter)
    assert isinstance(get_adapter("dataform"), DataformAdapter)


def test_custom_registered_adapter():
    from tff.core.adapter import ADAPTER_CLASSES

    ADAPTER_CLASSES["concrete_dummy"] = ("test_adapter", "ConcreteDummyAdapter")
    try:
        adapter = get_adapter("concrete_dummy")
        assert isinstance(adapter, ConcreteDummyAdapter)
    finally:
        ADAPTER_CLASSES.pop("concrete_dummy", None)


def test_get_adapter_unknown():
    with pytest.raises(ValueError, match="Unknown provider: unknown"):
        get_adapter("unknown")


def test_get_adapter_import_errors():
    with patch("importlib.import_module", side_effect=ImportError("mocked dbt")):
        with pytest.raises(ImportError, match="tff-core\\[dbt\\]"):
            get_adapter("dbt")

    with patch("importlib.import_module", side_effect=ImportError("mocked sqlmesh")):
        with pytest.raises(ImportError, match="tff-core\\[sqlmesh\\]"):
            get_adapter("sqlmesh")

    with patch("importlib.import_module", side_effect=ImportError("mocked dataform")):
        with pytest.raises(ImportError, match="tff-core\\[dataform\\]"):
            get_adapter("dataform")


def test_detect_provider(tmp_path: Path):
    # Empty
    with pytest.raises(ValueError, match="Could not detect project type"):
        detect_provider(tmp_path)

    # dbt
    (tmp_path / "dbt_project.yml").touch()
    assert detect_provider(tmp_path) == "dbt"

    # dbt + sqlmesh (ambiguous)
    (tmp_path / "config.py").touch()
    with pytest.raises(ValueError, match="Both dbt and SQLMesh"):
        detect_provider(tmp_path)

    # Clean dbt
    (tmp_path / "dbt_project.yml").unlink()
    assert detect_provider(tmp_path) == "sqlmesh"

    # Clean sqlmesh
    (tmp_path / "config.py").unlink()

    # sqlmesh alternatives
    for sig in (".sqlmesh", "config.yaml", "config.yml"):
        p = tmp_path / sig
        p.touch()
        assert detect_provider(tmp_path) == "sqlmesh"
        p.unlink()

    # dataform
    (tmp_path / "workflow_settings.yaml").touch()
    assert detect_provider(tmp_path) == "dataform"
    (tmp_path / "workflow_settings.yaml").unlink()

    (tmp_path / "dataform.json").touch()
    assert detect_provider(tmp_path) == "dataform"

    # multiple detected (e.g. dataform and sqlmesh)
    (tmp_path / "config.yaml").touch()
    with pytest.raises(ValueError, match="Multiple pipeline configuration files"):
        detect_provider(tmp_path)


def test_dbt_adapter(tmp_path: Path):
    adapter = DBTAdapter()
    assert adapter.provider_name == "dbt"

    assert not adapter.is_applicable(tmp_path)
    (tmp_path / "dbt_project.yml").touch()
    assert adapter.is_applicable(tmp_path)

    with patch(
        "tff.dbt.manifest.load_dbt_models", return_value={"m": MagicMock()}
    ) as mock_load:
        models = adapter.load_models(tmp_path, dialect="duckdb")
        assert "m" in models
        mock_load.assert_called_once_with(tmp_path, dialect="duckdb")

    cfg = FitnessFunctionsConfig()
    with patch(
        "tff.dbt.runner.run_all_checks", return_value=([], 1, ["rules"])
    ) as mock_run:
        res = adapter.run_checks(
            tmp_path, cfg, checks=["rules"], dialect="duckdb", models=models
        )
        assert res == ([], 1, ["rules"])
        mock_run.assert_called_once_with(
            project_root=tmp_path,
            config=cfg,
            checks=["rules"],
            dialect="duckdb",
            models=models,
        )

    with patch("tff.core.autofix.fix_dbt_metadata", return_value="fixed") as mock_fix:
        res = adapter.apply_metadata_fix(
            tmp_path, tmp_path / "models/m.sql", "m", True, False
        )
        assert res == "fixed"
        mock_fix.assert_called_once()

    diag = adapter.get_diagnostic_files(tmp_path)
    assert len(diag) == 2
    assert diag[0][0] == "dbt_project.yml"
    assert "found" in diag[0][1]
    assert diag[1][0] == "manifest.json"
    assert "missing" in diag[1][1]


def test_sqlmesh_adapter(tmp_path: Path):
    adapter = SQLMeshAdapter()
    assert adapter.provider_name == "sqlmesh"

    assert not adapter.is_applicable(tmp_path)
    (tmp_path / "config.py").touch()
    assert adapter.is_applicable(tmp_path)

    with (
        patch("sqlmesh.core.context.Context") as mock_ctx,
        patch(
            "tff.sqlmesh.runner.map_sqlmesh_context_models",
            return_value={"m": MagicMock()},
        ),
    ):
        models = adapter.load_models(tmp_path)
        assert "m" in models
        mock_ctx.assert_called_once()

    cfg = FitnessFunctionsConfig()
    with patch(
        "tff.sqlmesh.runner.run_all_checks", return_value=([], 1, ["sqlmesh"])
    ) as mock_run:
        res = adapter.run_checks(tmp_path, cfg, checks=["sqlmesh"], models=models)
        assert res == ([], 1, ["sqlmesh"])
        mock_run.assert_called_once_with(
            project_root=tmp_path,
            config=cfg,
            checks=["sqlmesh"],
            models=models,
        )

    with patch(
        "tff.core.autofix.fix_sqlmesh_metadata", return_value="fixed"
    ) as mock_fix:
        res = adapter.apply_metadata_fix(
            tmp_path, tmp_path / "models/m.sql", "m", True, False
        )
        assert res == "fixed"
        mock_fix.assert_called_once()

    diag = adapter.get_diagnostic_files(tmp_path)
    assert len(diag) == 2
    assert diag[0][0] == "config.py"
    assert "found" in diag[0][1]
    assert diag[1][0] == "settings.yaml"
    assert "missing" in diag[1][1]


def test_dataform_adapter(tmp_path: Path):
    adapter = DataformAdapter()
    assert adapter.provider_name == "dataform"

    assert not adapter.is_applicable(tmp_path)
    (tmp_path / "workflow_settings.yaml").touch()
    assert adapter.is_applicable(tmp_path)

    with patch(
        "tff.dataform.manifest.load_dataform_models", return_value={"m": MagicMock()}
    ) as mock_load:
        models = adapter.load_models(
            tmp_path, dialect="bigquery", manifest_path=Path("manifest.json")
        )
        assert "m" in models
        mock_load.assert_called_once_with(
            project_root=tmp_path,
            manifest_path=Path("manifest.json"),
            dialect="bigquery",
        )

    cfg = FitnessFunctionsConfig()
    with patch(
        "tff.dataform.runner.run_all_checks", return_value=([], 1, ["rules"])
    ) as mock_run:
        res = adapter.run_checks(
            tmp_path,
            cfg,
            checks=["rules"],
            dialect="bigquery",
            manifest_path="manifest.json",
            models=models,
        )
        assert res == ([], 1, ["rules"])
        mock_run.assert_called_once_with(
            project_root=tmp_path,
            config=cfg,
            checks=["rules"],
            dialect="bigquery",
            manifest_path="manifest.json",
            models=models,
        )

    assert (
        adapter.apply_metadata_fix(
            tmp_path, tmp_path / "definitions/m.sqlx", "m", True, False
        )
        is None
    )

    diag = adapter.get_diagnostic_files(tmp_path)
    assert len(diag) == 2
    assert diag[0][0] == "workflow_settings.yaml"
    assert "found" in diag[0][1]
    assert diag[1][0] == "compilation manifest"

    # dataform.json diagnostic branch
    (tmp_path / "workflow_settings.yaml").unlink()
    (tmp_path / "dataform.json").touch()
    diag2 = adapter.get_diagnostic_files(tmp_path)
    assert diag2[0][0] == "dataform.json"
    assert "found" in diag2[0][1]

    # missing diagnostic branch
    (tmp_path / "dataform.json").unlink()
    diag3 = adapter.get_diagnostic_files(tmp_path)
    assert diag3[0][0] == "workflow_settings.yaml"
    assert "missing" in diag3[0][1]


def test_mock_runner_adapter_all_methods(tmp_path: Path):
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 3, ["rules"])

    # dbt
    dbt_adapter = _MockRunnerAdapter("dbt", mock_runner)
    assert dbt_adapter.provider_name == "dbt"
    assert dbt_adapter.is_applicable(tmp_path) is True
    with patch("tff.dbt.manifest.load_dbt_models", return_value={"m1": MagicMock()}):
        assert "m1" in dbt_adapter.load_models(tmp_path, dialect="duckdb")
    cfg = FitnessFunctionsConfig()
    assert dbt_adapter.run_checks(
        tmp_path, cfg, dialect="duckdb", models={"m1": MagicMock()}
    ) == ([], 3, ["rules"])
    with patch("tff.core.autofix.fix_dbt_metadata", return_value="fixed"):
        assert (
            dbt_adapter.apply_metadata_fix(
                tmp_path, tmp_path / "models/m.sql", "m", True, True
            )
            == "fixed"
        )
    assert len(dbt_adapter.get_diagnostic_files(tmp_path)) == 2

    # sqlmesh
    sqlmesh_adapter = _MockRunnerAdapter("sqlmesh", mock_runner)
    assert sqlmesh_adapter.provider_name == "sqlmesh"
    with (
        patch("sqlmesh.core.context.Context"),
        patch(
            "tff.sqlmesh.runner.map_sqlmesh_context_models",
            return_value={"m2": MagicMock()},
        ),
    ):
        assert "m2" in sqlmesh_adapter.load_models(tmp_path)
    assert sqlmesh_adapter.run_checks(tmp_path, cfg, models={"m2": MagicMock()}) == (
        [],
        3,
        ["rules"],
    )
    with patch("tff.core.autofix.fix_sqlmesh_metadata", return_value="fixed_sm"):
        assert (
            sqlmesh_adapter.apply_metadata_fix(
                tmp_path, tmp_path / "models/m.sql", "m", True, True
            )
            == "fixed_sm"
        )
    assert len(sqlmesh_adapter.get_diagnostic_files(tmp_path)) == 2

    # dataform
    df_adapter = _MockRunnerAdapter("dataform", mock_runner)
    assert df_adapter.provider_name == "dataform"
    with patch(
        "tff.dataform.manifest.load_dataform_models", return_value={"m3": MagicMock()}
    ):
        assert "m3" in df_adapter.load_models(tmp_path)
    assert df_adapter.run_checks(
        tmp_path,
        cfg,
        dialect="bigquery",
        manifest_path="m.json",
        models={"m3": MagicMock()},
    ) == ([], 3, ["rules"])

    # other/unknown provider
    other_adapter = _MockRunnerAdapter("other", mock_runner)
    assert other_adapter.load_models(tmp_path) == {}
    assert (
        other_adapter.apply_metadata_fix(tmp_path, tmp_path / "x", "m", True, True)
        is None
    )
    assert other_adapter.get_diagnostic_files(tmp_path) == []


def test_cli_info_adapter_error(tmp_path: Path):
    with patch(
        "tff.core.cli._get_adapter", side_effect=ValueError("Test adapter error")
    ):
        assert main(["info", "--project", str(tmp_path), "--provider", "dbt"]) == 1


def test_cli_get_adapter():
    assert isinstance(_get_adapter("dbt"), DBTAdapter)
