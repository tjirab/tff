import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tff.core.cli import _detect_provider, _get_runner, main


def test_detect_provider_dbt(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    assert _detect_provider(tmp_path) == "dbt"


def test_detect_provider_sqlmesh_py(tmp_path: Path):
    (tmp_path / "config.py").touch()
    assert _detect_provider(tmp_path) == "sqlmesh"


def test_detect_provider_sqlmesh_yaml(tmp_path: Path):
    (tmp_path / "config.yaml").touch()
    assert _detect_provider(tmp_path) == "sqlmesh"


def test_detect_provider_sqlmesh_yml(tmp_path: Path):
    (tmp_path / "config.yml").touch()
    assert _detect_provider(tmp_path) == "sqlmesh"


def test_detect_provider_sqlmesh_dir(tmp_path: Path):
    (tmp_path / ".sqlmesh").mkdir()
    assert _detect_provider(tmp_path) == "sqlmesh"


def test_detect_provider_conflict(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    (tmp_path / "config.py").touch()
    with pytest.raises(ValueError, match="Both dbt and SQLMesh configuration files were detected"):
        _detect_provider(tmp_path)


def test_detect_provider_not_found(tmp_path: Path):
    with pytest.raises(ValueError, match="Could not detect project type"):
        _detect_provider(tmp_path)


def test_get_runner_success_dbt():
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_import.return_value = mock_module
        runner = _get_runner("dbt")
        mock_import.assert_called_once_with("tff.dbt.runner")
        assert runner == mock_module


def test_get_runner_success_sqlmesh():
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_import.return_value = mock_module
        runner = _get_runner("sqlmesh")
        mock_import.assert_called_once_with("tff.sqlmesh.runner")
        assert runner == mock_module


def test_get_runner_import_error_dbt():
    with patch("importlib.import_module", side_effect=ImportError("No module named 'tff.dbt.runner'")):
        with pytest.raises(ImportError, match="tff-dbt is not installed"):
            _get_runner("dbt")


def test_get_runner_import_error_sqlmesh():
    with patch("importlib.import_module", side_effect=ImportError("No module named 'tff.sqlmesh.runner'")):
        with pytest.raises(ImportError, match="tff-sqlmesh is not installed"):
            _get_runner("sqlmesh")


def test_get_runner_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        _get_runner("unknown_provider")


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_dbt(
    mock_render,
    mock_load_config,
    mock_get_runner,
    mock_detect_provider,
    tmp_path: Path,
):
    mock_detect_provider.return_value = "dbt"
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 5, ["rules"])
    mock_get_runner.return_value = mock_runner
    mock_render.return_value = True

    # Run the main cli
    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--dialect", "duckdb"])

    assert exit_code == 0
    mock_detect_provider.assert_called_once()
    mock_get_runner.assert_called_once_with("dbt")
    mock_runner.run_all_checks.assert_called_once_with(
        project_root=tmp_path.resolve(),
        config=mock_load_config.return_value,
        checks=None,
        dialect="duckdb",
    )
    mock_render.assert_called_once_with(
        [],
        models_checked=5,
        executed_checks=["rules"],
        fail_level="error",
        group_by="connascence",
    )


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_sqlmesh_explicit_provider(
    mock_render,
    mock_load_config,
    mock_get_runner,
    tmp_path: Path,
):
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 10, ["sqlmesh"])
    mock_get_runner.return_value = mock_runner
    mock_render.return_value = False  # Failed report

    # Run the main cli with explicit provider
    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--provider", "sqlmesh", "--checks", "sqlmesh,layer_integrity"])

    assert exit_code == 1  # Since mock_render returned False
    mock_get_runner.assert_called_once_with("sqlmesh")
    mock_runner.run_all_checks.assert_called_once_with(
        project_root=tmp_path.resolve(),
        config=mock_load_config.return_value,
        checks=["sqlmesh", "layer_integrity"],
    )


@patch("tff.core.cli._detect_provider")
def test_main_lint_detect_failure(mock_detect_provider, tmp_path: Path):
    mock_detect_provider.side_effect = ValueError("No project found")
    
    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str])
    assert exit_code == 1


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_runner")
def test_main_lint_import_error_exit(mock_get_runner, mock_detect_provider, tmp_path: Path):
    mock_detect_provider.return_value = "dbt"
    mock_get_runner.side_effect = ImportError("Not installed")
    
    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str])
    assert exit_code == 1


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
def test_main_lint_load_config_error(mock_load_config, mock_get_runner, tmp_path: Path):
    mock_load_config.side_effect = Exception("Config load failed")
    mock_runner = MagicMock()
    mock_get_runner.return_value = mock_runner

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--provider", "dbt"])
    assert exit_code == 1


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_sqlmesh_dialect_warning(
    mock_render, mock_load_config, mock_get_runner, tmp_path: Path
):
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 0, [])
    mock_get_runner.return_value = mock_runner
    mock_render.return_value = True

    project_str = str(tmp_path)
    with patch("sys.stderr", new_callable=MagicMock) as mock_stderr:
        exit_code = main(
            ["lint", "--project", project_str, "--provider", "sqlmesh", "--dialect", "duckdb"]
        )
        assert exit_code == 0
        # Check that warning was printed
        written = "".join(call.args[0] for call in mock_stderr.write.call_args_list)
        assert "Warning: --dialect is ignored" in written


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
def test_main_lint_run_checks_error(mock_load_config, mock_get_runner, tmp_path: Path):
    mock_runner = MagicMock()
    mock_runner.run_all_checks.side_effect = Exception("Check execution failed")
    mock_get_runner.return_value = mock_runner

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--provider", "dbt"])
    assert exit_code == 1


def test_cli_main_block(tmp_path: Path):
    import runpy

    # Patch original source modules so that runpy imports pick up the mocks
    with patch("importlib.import_module") as mock_import, \
         patch("tff.core.config.load_fitness_config"), \
         patch("tff.core.report.render_lint_report") as mock_render:
         
        mock_runner = MagicMock()
        mock_runner.run_all_checks.return_value = ([], 0, [])
        mock_import.return_value = mock_runner
        mock_render.return_value = True

        project_str = str(tmp_path)
        orig_argv = sys.argv
        sys.argv = ["tff", "lint", "--project", project_str, "--provider", "dbt"]
        try:
            with pytest.raises(SystemExit) as excinfo:
                runpy.run_module("tff.core.cli", run_name="__main__")
            assert excinfo.value.code == 0
        finally:
            sys.argv = orig_argv
            
        mock_import.assert_any_call("tff.dbt.runner")
        mock_runner.run_all_checks.assert_called_once()


def test_main_unhandled_command():
    with patch("argparse.ArgumentParser.parse_args") as mock_parse_args:
        mock_args = MagicMock()
        mock_args.command = "some_other_cmd"
        mock_parse_args.return_value = mock_args

        exit_code = main([])
        assert exit_code == 1







