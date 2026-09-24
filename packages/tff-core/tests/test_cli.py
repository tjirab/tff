import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tff.core.cli import _detect_provider, _get_runner, main, mask_sensitive_args


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
    with pytest.raises(
        ValueError, match="Both dbt and SQLMesh configuration files were detected"
    ):
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
    with patch(
        "importlib.import_module",
        side_effect=ImportError("No module named 'tff.dbt.runner'"),
    ):
        with pytest.raises(ImportError, match="tff is not installed with dbt support"):
            _get_runner("dbt")


def test_get_runner_import_error_sqlmesh():
    with patch(
        "importlib.import_module",
        side_effect=ImportError("No module named 'tff.sqlmesh.runner'"),
    ):
        with pytest.raises(
            ImportError, match="tff is not installed with sqlmesh support"
        ):
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
    assert mock_render.call_count == 1
    call_args, call_kwargs = mock_render.call_args
    assert call_args == ([],)
    assert call_kwargs["models_checked"] == 5
    assert call_kwargs["executed_checks"] == ["rules"]
    assert call_kwargs["fail_level"] == "error"
    assert call_kwargs["group_by"] == "model"
    assert call_kwargs["duration"] is not None


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
    exit_code = main(
        [
            "lint",
            "--project",
            project_str,
            "--provider",
            "sqlmesh",
            "--checks",
            "sqlmesh,layer_integrity",
        ]
    )

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
def test_main_lint_import_error_exit(
    mock_get_runner, mock_detect_provider, tmp_path: Path
):
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
            [
                "lint",
                "--project",
                project_str,
                "--provider",
                "sqlmesh",
                "--dialect",
                "duckdb",
            ]
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


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_group_by_connascence(
    mock_render, mock_load_config, mock_get_runner, tmp_path: Path
):
    """Test that --group-by connascence is forwarded to render_lint_report."""
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 5, ["rules"])
    mock_get_runner.return_value = mock_runner
    mock_render.return_value = True

    project_str = str(tmp_path)
    exit_code = main(
        [
            "lint",
            "--project",
            project_str,
            "--provider",
            "dbt",
            "--group-by",
            "connascence",
        ]
    )

    assert exit_code == 0
    assert mock_render.call_count == 1
    call_args, call_kwargs = mock_render.call_args
    assert call_args == ([],)
    assert call_kwargs["models_checked"] == 5
    assert call_kwargs["executed_checks"] == ["rules"]
    assert call_kwargs["fail_level"] == "error"
    assert call_kwargs["group_by"] == "connascence"
    assert call_kwargs["duration"] is not None


def test_cli_main_block(tmp_path: Path):
    import runpy

    # Patch original source modules so that runpy imports pick up the mocks
    with (
        patch("importlib.import_module") as mock_import,
        patch("tff.core.config.load_fitness_config"),
        patch("tff.core.report.render_lint_report") as mock_render,
    ):
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


def test_help_subcommand(capsys):
    # Test tff help
    assert main(["help"]) == 0
    captured = capsys.readouterr()
    assert "Run Transformation Fitness Function (tff) checks" in captured.out

    # Test tff help lint
    assert main(["help", "lint"]) == 0
    captured = capsys.readouterr()
    assert "--fail-level" in captured.out

    # Test tff help health
    assert main(["help", "health"]) == 0
    captured = capsys.readouterr()
    assert "--fail-under" in captured.out

    # Test tff help docs
    assert main(["help", "docs"]) == 0
    captured = capsys.readouterr()
    assert "--output" in captured.out

    # Test tff help init
    assert main(["help", "init"]) == 0
    captured = capsys.readouterr()
    assert "--force" in captured.out


def test_invalid_command_error_hint(capsys):
    # Test tff foo
    with pytest.raises(SystemExit) as excinfo:
        main(["foo"])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice: 'foo'" in captured.err
    assert "For help, try 'tff --help'" in captured.err


def test_missing_command_defaults_to_help(capsys):
    # Test tff (no command) defaults to showing help and exiting 0
    assert main([]) == 0
    captured = capsys.readouterr()
    assert "Run Transformation Fitness Function (tff) checks" in captured.out
    assert "tff" in captured.out


def test_version_flag_long(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "tff" in captured.out


def test_version_flag_short(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["-v"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "tff" in captured.out


def test_main_no_argv_defaults_to_help(capsys):
    with patch("sys.argv", ["tff"]):
        assert main() == 0
        captured = capsys.readouterr()
        assert "Run Transformation Fitness Function (tff) checks" in captured.out


def test_subcommand_invalid_argument_error_hint(capsys):
    # Test tff lint --invalid-option
    with pytest.raises(SystemExit) as excinfo:
        main(["lint", "--invalid-option"])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "unrecognized arguments: --invalid-option" in captured.err
    assert "For help, try 'tff lint --help'" in captured.err


def test_help_info_subcommand(capsys):
    assert main(["help", "info"]) == 0
    captured = capsys.readouterr()
    assert "Show configuration and environment information" in captured.out
    assert "--provider" in captured.out


def test_info_command_dbt(tmp_path: Path, capsys):
    dbt_project = tmp_path / "dbt_project.yml"
    dbt_project.touch()

    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text(
        "contract_groups_path: linter_contract_groups.json\nexclusions_path: linter_exclusions.json"
    )

    (tmp_path / "linter_contract_groups.json").touch()
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").touch()

    import importlib.metadata

    with patch("importlib.metadata.version") as mock_version:

        def mock_version_side_effect(pkg):
            if pkg == "tff-core":
                return "1.0.0"
            raise importlib.metadata.PackageNotFoundError("Package not found")

        mock_version.side_effect = mock_version_side_effect
        exit_code = main(
            ["info", "--project", str(tmp_path), "--config", "fitness_functions.yaml"]
        )
        assert exit_code == 0
        captured = capsys.readouterr()

        assert "tff Info" in captured.out
        assert "Project root:" in captured.out
        assert "Provider:" in captured.out
        assert "dbt" in captured.out
        assert "fitness_functions.yaml" in captured.out
        assert "Contract groups:" in captured.out
        assert "Exclusions:" in captured.out
        assert "Adapter Versions" in captured.out
        assert "tff-core" in captured.out
        assert "dbt integration" in captured.out
        assert "Provider Files" in captured.out
        assert "dbt_project.yml" in captured.out
        assert "manifest.json" in captured.out


def test_info_command_sqlmesh(tmp_path: Path, capsys):
    (tmp_path / "config.py").touch()

    with patch("importlib.metadata.version") as mock_version:
        mock_version.return_value = "0.1.0"
        exit_code = main(["info", "--project", str(tmp_path), "--provider", "sqlmesh"])
        assert exit_code == 0
        captured = capsys.readouterr()

        assert "sqlmesh" in captured.out
        assert "config.py" in captured.out
        assert "settings.yaml" in captured.out


def test_info_command_detect_failure(tmp_path: Path, capsys):
    exit_code = main(["info", "--project", str(tmp_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Error detecting provider" in captured.out


def test_info_command_invalid_config(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text("invalid: yaml: content: :")

    exit_code = main(
        ["info", "--project", str(tmp_path), "--config", "fitness_functions.yaml"]
    )
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Failed to load config:" in captured.out


def test_argv_fallback_error(capsys):
    from tff.core.cli import TffArgumentParser, TFFArgumentParser

    assert TFFArgumentParser is TffArgumentParser
    parser = TffArgumentParser(prog="tff")
    TffArgumentParser._current_argv = None

    with patch("sys.argv", ["tff", "lint", "--invalid-arg"]):
        with pytest.raises(SystemExit) as excinfo:
            parser.error("some error")
        assert excinfo.value.code == 2
        captured = capsys.readouterr()
        assert "For help, try 'tff lint --help'" in captured.err


def test_info_command_with_virtualenv(tmp_path: Path, capsys):
    # Setup simulated project root
    (tmp_path / "config.py").touch()

    # Create simulated virtualenv site-packages
    site_packages = tmp_path / ".venv" / "lib" / "python3.13" / "site-packages"
    site_packages.mkdir(parents=True)

    # Create dist-info directories for metadata
    tff_core_dist = site_packages / "tff_core-1.2.3.dist-info"
    tff_core_dist.mkdir()
    (tff_core_dist / "METADATA").write_text("Name: tff-core\nVersion: 1.2.3\n")

    # Create Windows-style virtualenv site-packages for coverage
    win_site_packages = tmp_path / ".venv" / "Lib" / "site-packages"
    win_site_packages.mkdir(parents=True)
    win_tff_core_dist = win_site_packages / "tff_core-1.2.3.dist-info"
    win_tff_core_dist.mkdir()
    (win_tff_core_dist / "METADATA").write_text("Name: tff-core\nVersion: 1.2.3\n")

    exit_code = main(["info", "--project", str(tmp_path), "--provider", "sqlmesh"])
    assert exit_code == 0
    captured = capsys.readouterr()

    # Verify that the versions from the simulated virtualenv are displayed
    assert "tff-core" in captured.out
    assert "1.2.3" in captured.out
    assert "sqlmesh integration" in captured.out
    assert "dbt integration" in captured.out


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_json(
    mock_render,
    mock_load_config,
    mock_get_runner,
    mock_detect_provider,
    tmp_path: Path,
    capsys,
):
    mock_detect_provider.return_value = "dbt"
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 5, ["rules"])
    mock_get_runner.return_value = mock_runner

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--json"])

    assert exit_code == 0
    mock_render.assert_not_called()

    captured = capsys.readouterr()
    import json

    data = json.loads(captured.out)
    assert data["command"] == "lint"
    assert data["models_checked"] == 5
    assert data["passed"] is True

    # Verify log file was written
    log_files = list((tmp_path / ".tff_logs" / "lint").glob("*.log"))
    assert len(log_files) == 1


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_no_log(
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

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--no-log"])

    assert exit_code == 0
    assert not (tmp_path / ".tff_logs").exists()


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_main_health_normal_and_json(
    mock_render_health,
    mock_load_config,
    mock_get_runner,
    mock_detect_provider,
    tmp_path: Path,
    capsys,
):
    mock_detect_provider.return_value = "dbt"
    mock_runner = MagicMock()
    # health command expects findings, models_checked, executed_checks
    mock_runner.run_all_checks.return_value = ([], 8, ["rules"])
    mock_get_runner.return_value = mock_runner

    # 1. Run without --json
    project_str = str(tmp_path)
    exit_code = main(["health", "--project", project_str])
    assert exit_code == 0
    mock_render_health.assert_called_once()
    mock_render_health.reset_mock()

    log_files = list((tmp_path / ".tff_logs" / "health").glob("*.log"))
    assert len(log_files) == 1
    # Clean up logs for the next run
    for lf in log_files:
        lf.unlink()

    # 2. Run with --json
    exit_code_json = main(["health", "--project", project_str, "--json"])
    assert exit_code_json == 0
    mock_render_health.assert_not_called()

    captured = capsys.readouterr()
    import json

    data = json.loads(captured.out)
    assert data["command"] == "health"
    assert data["models_checked"] == 8
    assert data["overall_score"] == 100.0

    # Verify log file was written again
    log_files = list((tmp_path / ".tff_logs" / "health").glob("*.log"))
    assert len(log_files) == 1


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_main_health_no_log(
    mock_render_health,
    mock_load_config,
    mock_get_runner,
    mock_detect_provider,
    tmp_path: Path,
):
    mock_detect_provider.return_value = "dbt"
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 8, ["rules"])
    mock_get_runner.return_value = mock_runner

    project_str = str(tmp_path)
    exit_code = main(["health", "--project", project_str, "--no-log"])
    assert exit_code == 0
    assert not (tmp_path / ".tff_logs").exists()


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_main_health_with_scope(
    mock_render_health,
    mock_load_config,
    mock_get_runner,
    mock_detect_provider,
    tmp_path: Path,
    capsys,
):
    mock_detect_provider.return_value = "dbt"
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 8, ["rules"])
    mock_get_runner.return_value = mock_runner

    # Create dummy scoped files
    marts_dir = tmp_path / "models" / "marts"
    marts_dir.mkdir(parents=True)
    (marts_dir / "m1.sql").write_text("SELECT 1")
    (marts_dir / "m2.sql").write_text("SELECT 2")

    project_str = str(tmp_path)
    exit_code = main(["health", "--project", project_str, "--scope", "models/marts", "--json"])
    assert exit_code == 0

    import json
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["command"] == "health"
    assert data["models_checked"] == 2
    assert data["overall_score"] == 100.0

    # Test file-specific scope
    exit_code_file = main(["health", "--project", project_str, "--scope", "models/marts/m1.sql", "--json"])
    assert exit_code_file == 0
    captured_file = capsys.readouterr()
    data_file = json.loads(captured_file.out)
    assert data_file["models_checked"] == 1


def test_main_stats_no_logs(tmp_path: Path, capsys):
    # Running stats when no logs exist should exit 1 and show error
    project_str = str(tmp_path)
    exit_code = main(["stats", "--project", project_str])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "No tff run logs found" in captured.err


def test_main_stats(tmp_path: Path, capsys):
    project_str = str(tmp_path)
    # Create mock logs
    health_dir = tmp_path / ".tff_logs" / "health"
    health_dir.mkdir(parents=True)
    import json

    # Write a health log
    with open(health_dir / "h1.log", "w", encoding="utf-8") as f:
        json.dump({"timestamp": "2026-07-03T12:00:00+02:00", "overall_score": 92.5}, f)

    # 1. Run stats command (ASCII output)
    exit_code = main(["stats", "--project", project_str])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "tff Project Health Score Trend" in captured.out
    assert "Summary History" in captured.out
    assert "92.5%" in captured.out

    # 2. Run stats command with --json flag
    exit_code_json = main(["stats", "--project", project_str, "--json"])
    assert exit_code_json == 0
    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert data["days"] == 7
    assert len(data["history"]) == 7
    assert data["history"][-1]["health_score"] == 92.5


def test_help_stats_subcommand(capsys):
    assert main(["help", "stats"]) == 0
    captured = capsys.readouterr()
    assert "Show history and trends of fitness checks" in captured.out
    assert "--days" in captured.out
    assert "-p" in captured.out
    assert "--project" in captured.out


def test_main_stats_variations(tmp_path: Path, capsys):
    project_str = str(tmp_path)
    lint_dir = tmp_path / ".tff_logs" / "lint"
    lint_dir.mkdir(parents=True)
    import json

    # Write a lint log (with errors and warnings)
    with open(lint_dir / "l1.log", "w", encoding="utf-8") as f:
        json.dump(
            {
                "timestamp": "2026-07-03T12:00:00+02:00",
                "errors_count": 2,
                "warnings_count": 3,
            },
            f,
        )

    # 1. Run stats command (ASCII output)
    # This covers:
    # - No health score data in this timeframe
    # - Lint violations trend rendering
    # - non-zero errors and warnings in table rows
    exit_code = main(["stats", "--project", project_str])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "No health score data in this timeframe" in captured.out
    assert "tff Lint Violations Trend" in captured.out
    assert "Summary History" in captured.out

    # 2. Test invalid date parsing exception handling in summary table formatting
    # Mock collect_stats to return history containing an invalid date
    with patch("tff.core.logs.collect_stats") as mock_collect:
        mock_collect.return_value = [
            {
                "date": "invalid-date-format",
                "health_score": 90.0,
                "errors_count": 0,
                "warnings_count": 0,
            }
        ]
        exit_code_mock = main(["stats", "--project", project_str])
        assert exit_code_mock == 0
        captured_mock = capsys.readouterr()
        assert "invalid-date-format" in captured_mock.out


def test_cli_version_fallback():
    with patch(
        "importlib.metadata.version", side_effect=Exception("Package not found")
    ):
        import importlib
        import tff.core.cli

        importlib.reload(tff.core.cli)
        assert tff.core.cli.__version__ == "0.7.0"

    # Restore original by reloading again without patch
    import importlib
    import tff.core.cli

    importlib.reload(tff.core.cli)


def test_cli_main_lint_with_fix(tmp_path: Path):
    from tff.core.report import LintFinding
    from tff.core.model import ModelRepresentation
    # Create dbt_project.yml to auto-detect provider
    (tmp_path / "dbt_project.yml").touch()

    # Create a sql file containing positional GROUP BY
    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT a FROM t GROUP BY 1", encoding="utf-8")

    # Mock runner run_all_checks to return initial findings
    mock_runner = MagicMock()
    # 1st call returns finding, 2nd call (re-run) returns empty findings
    mock_runner.run_all_checks.side_effect = [
        (
            [
                LintFinding(
                    check="nopositionalgroupbyororderby",
                    severity="error",
                    model="my_model",
                    path="models/marts/my_model.sql",
                    message="Use column name instead."
                )
            ],
            1,
            ["rules"]
        ),
        (
            [],
            1,
            ["rules"]
        )
    ]

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config, \
         patch("tff.core.cli.render_lint_report", return_value=True):
        
        mock_load_config.return_value = MagicMock()
        
        # We need to mock load_dbt_models to return ModelRepresentation
        with patch("tff.dbt.manifest.load_dbt_models") as mock_load_dbt_models:
            mock_load_dbt_models.return_value = {
                "my_model": ModelRepresentation(
                    name="my_model",
                    path=str(sql_file),
                    dialect="ansi"
                )
            }
            
            exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
            
            assert exit_code == 0
            # Verify file was updated
            assert sql_file.read_text(encoding="utf-8") == "SELECT a FROM t GROUP BY a"
            assert mock_runner.run_all_checks.call_count == 2


def test_cli_main_lint_with_fix_sqlmesh(tmp_path: Path):
    from tff.core.report import LintFinding
    from tff.core.model import ModelRepresentation
    
    # Create config.py to auto-detect provider as SQLMesh
    (tmp_path / "config.py").touch()
    
    # Create a SQL file
    sql_file = tmp_path / "models/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT a FROM t GROUP BY 1", encoding="utf-8")
    
    # Mock runner
    mock_runner = MagicMock()
    mock_runner.run_all_checks.side_effect = [
        (
            [
                LintFinding(
                    check="nopositionalgroupbyororderby",
                    severity="error",
                    model="my_model",
                    path="models/my_model.sql",
                    message="Use column name instead."
                )
            ],
            1,
            ["sqlmesh"]
        ),
        (
            [],
            1,
            ["sqlmesh"]
        )
    ]
    
    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config, \
         patch("tff.core.cli.render_lint_report", return_value=True), \
         patch("sqlmesh.core.context.Context"), \
         patch("tff.sqlmesh.runner.map_sqlmesh_context_models") as mock_map_models:
        
        mock_load_config.return_value = MagicMock()
        mock_map_models.return_value = {
            "my_model": ModelRepresentation(
                name="my_model",
                path=str(sql_file),
                dialect="ansi"
            )
        }
        
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 0
        assert sql_file.read_text(encoding="utf-8") == "SELECT a FROM t GROUP BY a"
        assert mock_runner.run_all_checks.call_count == 2


def test_cli_main_lint_with_fix_load_models_exception(tmp_path: Path):
    from tff.core.report import LintFinding
    (tmp_path / "dbt_project.yml").touch()
    
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = (
        [
            LintFinding(
                check="nopositionalgroupbyororderby",
                severity="error",
                model="my_model",
                path="models/my_model.sql",
                message="Use column name instead."
            )
        ],
        1,
        ["rules"]
    )
    
    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config, \
         patch("tff.core.cli.render_lint_report", return_value=False), \
         patch("tff.dbt.manifest.load_dbt_models", side_effect=Exception("Load failed")):
        
        mock_load_config.return_value = MagicMock()
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 1  # Should fail since it wasn't fixed and returned a finding
        assert mock_runner.run_all_checks.call_count == 1  # No re-run


def test_cli_main_lint_with_fix_rerun_exception(tmp_path: Path):
    from tff.core.report import LintFinding
    from tff.core.model import ModelRepresentation
    (tmp_path / "dbt_project.yml").touch()
    
    sql_file = tmp_path / "models/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT a FROM t GROUP BY 1", encoding="utf-8")
    
    mock_runner = MagicMock()
    mock_runner.run_all_checks.side_effect = [
        (
            [
                LintFinding(
                    check="nopositionalgroupbyororderby",
                    severity="error",
                    model="my_model",
                    path="models/my_model.sql",
                    message="Use column name instead."
                )
            ],
            1,
            ["rules"]
        ),
        Exception("Re-run failed")
    ]
    
    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config, \
         patch("tff.dbt.manifest.load_dbt_models") as mock_load_dbt_models:
        
        mock_load_config.return_value = MagicMock()
        mock_load_dbt_models.return_value = {
            "my_model": ModelRepresentation(
                name="my_model",
                path=str(sql_file),
                dialect="ansi"
            )
        }
        
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 1
        assert mock_runner.run_all_checks.call_count == 2


def test_cli_init_success(tmp_path: Path, capsys):
    exit_code = main(["init", "--project", str(tmp_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Created fitness_functions.yaml" in captured.out
    assert (tmp_path / "fitness_functions.yaml").exists()


def test_cli_init_already_exists_error(tmp_path: Path, capsys):
    (tmp_path / "fitness_functions.yaml").write_text("existing: true\n", encoding="utf-8")
    exit_code = main(["init", "--project", str(tmp_path)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "already exists" in captured.err
    assert "--force" in captured.err


def test_cli_init_force_overwrite(tmp_path: Path, capsys):
    (tmp_path / "fitness_functions.yaml").write_text("existing: true\n", encoding="utf-8")
    exit_code = main(["init", "--project", str(tmp_path), "--force"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Overwrote fitness_functions.yaml" in captured.out


def test_cli_init_unexpected_error(tmp_path: Path, capsys):
    with patch("tff.core.cli.init_fitness_config", side_effect=OSError("Disk full")):
        exit_code = main(["init", "--project", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error creating configuration file: Disk full" in captured.err


def test_cli_lint_missing_config_notice(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 0, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Notice: No fitness_functions.yaml found." in captured.err
        assert "staging -> intermediate -> core -> marts" in captured.err
        assert "Run 'tff init' to generate a project configuration file." in captured.err


def test_cli_lint_existing_config_no_notice(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    (tmp_path / "fitness_functions.yaml").write_text("layers:\n  order: [staging, marts]\n", encoding="utf-8")
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 0, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Notice: No fitness_functions.yaml found." not in captured.err


def test_cli_lint_json_no_notice(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 0, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path), "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Notice: No fitness_functions.yaml found." not in captured.err
        assert "Notice: No fitness_functions.yaml found." not in captured.out


def test_cli_health_missing_config_notice(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 0, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.health.render_health_report"):
        exit_code = main(["health", "--project", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Notice: No fitness_functions.yaml found." in captured.err
        assert "Run 'tff init' to generate a project configuration file." in captured.err


def test_cli_health_existing_config_no_notice(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    (tmp_path / "fitness_functions.yaml").write_text("layers:\n  order: [staging, marts]\n", encoding="utf-8")
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 0, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.health.render_health_report"):
        exit_code = main(["health", "--project", str(tmp_path)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Notice: No fitness_functions.yaml found." not in captured.err


def test_cli_lint_format_sarif(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    from tff.core.report import LintFinding

    finding = LintFinding(
        check="banselectstar",
        severity="error",
        message="SELECT * not allowed",
        model="model_a",
        path="models/model_a.sql",
        line=10,
    )
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "sarif"])
        assert exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        assert len(data["runs"][0]["results"]) == 1
        assert data["runs"][0]["results"][0]["ruleId"] == "banselectstar"


def test_cli_lint_format_json(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 1, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["command"] == "lint"
        assert data["passed"] is True


def test_cli_lint_format_text(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 1, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.render_lint_report", return_value=True) as mock_render:
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "text"])
        assert exit_code == 0
        mock_render.assert_called_once()


def test_cli_lint_github_annotations_flag(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    from tff.core.report import LintFinding

    finding = LintFinding(
        check="nomissingowner",
        severity="warning",
        message="Missing model owner",
        model="stg_users",
        path="models/staging/stg_users.sql",
        line=1,
    )
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([finding], 1, ["nomissingowner"])

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.render_lint_report", return_value=True):
        exit_code = main(["lint", "--project", str(tmp_path), "--github-annotations"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "::warning file=models/staging/stg_users.sql,line=1::Missing model owner" in captured.out


def test_cli_lint_github_actions_env(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tmp_path / "dbt_project.yml").touch()
    from tff.core.report import LintFinding

    finding = LintFinding(
        check="banselectstar",
        severity="error",
        message="SELECT * forbidden",
        model="fct_orders",
        path="models/marts/fct_orders.sql",
        line=25,
    )
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.render_lint_report", return_value=False):
        exit_code = main(["lint", "--project", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "::error file=models/marts/fct_orders.sql,line=25::SELECT * forbidden" in captured.out


def test_cli_lint_github_actions_env_sarif_no_annotations(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tmp_path / "dbt_project.yml").touch()
    from tff.core.report import LintFinding

    finding = LintFinding(
        check="banselectstar",
        severity="error",
        message="SELECT * forbidden",
        model="fct_orders",
        path="models/marts/fct_orders.sql",
    )
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "sarif"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "::error" not in captured.out
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"


def test_cli_lint_junit_xml(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 2, [])
    junit_target = tmp_path / "reports" / "junit.xml"

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("tff.core.cli.render_lint_report", return_value=True):
        exit_code = main(["lint", "--project", str(tmp_path), "--junit-xml", str(junit_target)])
        assert exit_code == 0
        assert junit_target.exists()
        content = junit_target.read_text(encoding="utf-8")
        assert "<testsuites" in content
        assert 'tests="1"' in content
        assert 'failures="0"' in content


def test_cli_lint_format_github_with_findings(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    from tff.core.report import LintFinding

    finding = LintFinding(
        check="banselectstar",
        severity="error",
        message="SELECT * not permitted in marts",
        model="fct_orders",
        path="models/marts/fct_orders.sql",
        line=12,
    )
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "github"])
        assert exit_code == 1
        captured = capsys.readouterr()
        # Only pure workflow command annotations in stdout, no rich summary table
        assert captured.out.strip() == "::error file=models/marts/fct_orders.sql,line=12::SELECT * not permitted in marts"
        assert "LINT FAILED" not in captured.out


def test_cli_lint_format_github_empty(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 5, [])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "github"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""


def test_cli_lint_structured_with_github_annotations(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    from tff.core.report import LintFinding

    finding = LintFinding(
        check="nomissingowner",
        severity="warning",
        message="Missing owner attribute",
        model="stg_customers",
        path="models/staging/stg_customers.sql",
        line=1,
    )
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([finding], 1, ["nomissingowner"])

    with patch("tff.core.cli._get_runner", return_value=mock_runner):
        # 1. SARIF with --github-annotations
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "sarif", "--github-annotations"])
        assert exit_code == 0
        captured = capsys.readouterr()
        # stdout is pure, parseable SARIF JSON
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        # annotations routed to stderr to prevent corrupting stdout
        assert "::warning file=models/staging/stg_customers.sql,line=1::Missing owner attribute" in captured.err

        # 2. JSON with --github-annotations
        exit_code_json = main(["lint", "--project", str(tmp_path), "--format", "json", "--github-annotations"])
        assert exit_code_json == 0
        captured_json = capsys.readouterr()
        # stdout is pure, parseable JSON
        data_json = json.loads(captured_json.out)
        assert data_json["command"] == "lint"
        assert "::warning file=models/staging/stg_customers.sql,line=1::Missing owner attribute" in captured_json.err


def test_cli_info_and_lint_with_plugins_and_custom_adapter(tmp_path: Path, capsys):
    from tff.core.adapter import PipelineAdapter, _REGISTERED_ADAPTERS, register_adapter

    class MyCustomEngineAdapter(PipelineAdapter):
        @property
        def provider_name(self) -> str:
            return "my_custom_engine"

        def is_applicable(self, project_root: Path) -> bool:
            return True

        def load_models(self, project_root: Path, dialect=None, manifest_path=None):
            return {}

        def run_checks(self, project_root: Path, config, checks=None, dialect=None, manifest_path=None, models=None):
            return [], 0, ["custom_rule"]

        def get_diagnostic_files(self, project_root: Path):
            return [("custom_config.yml", "found")]

    register_adapter("my_custom_engine", MyCustomEngineAdapter)
    adapter_inst = MyCustomEngineAdapter()
    assert adapter_inst.provider_name == "my_custom_engine"
    assert adapter_inst.is_applicable(tmp_path) is True
    assert adapter_inst.load_models(tmp_path) == {}

    try:
        # Create fitness_functions.yaml with plugin
        cfg_file = tmp_path / "fitness_functions.yaml"
        cfg_file.write_text("plugins:\n  - custom_plugin.py\n", encoding="utf-8")
        (tmp_path / "custom_plugin.py").write_text("# custom plugin\n", encoding="utf-8")


        # 1. Test info command
        exit_code_info = main([
            "info",
            "--project", str(tmp_path),
            "--provider", "my_custom_engine",
        ])
        assert exit_code_info == 0
        captured_info = capsys.readouterr()
        assert "my_custom_engine integration" in captured_info.out
        assert "Plugin:" in captured_info.out
        assert "custom_plugin.py" in captured_info.out
        assert "custom_config.yml" in captured_info.out

        # 2. Test lint command with custom provider
        exit_code_lint = main([
            "lint",
            "--project", str(tmp_path),
            "--provider", "my_custom_engine",
        ])
        assert exit_code_lint == 0
        captured_lint = capsys.readouterr()
        assert "LINT PASSED" in captured_lint.out
    finally:
        _REGISTERED_ADAPTERS.pop("my_custom_engine", None)


def test_cli_lint_workers_and_cache_flags(tmp_path: Path, capsys, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "dbt_project.yml").touch()
    (tmp_path / "fitness_functions.yaml").write_text("workers: 1\n", encoding="utf-8")
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text(
        '{"metadata": {"adapter_type": "duckdb"}, "nodes": {}, "sources": {}}',
        encoding="utf-8",
    )

    # 1. Test --workers and --no-cache
    exit_code = main([
        "lint",
        "--project", str(tmp_path),
        "--provider", "dbt",
        "--workers", "4",
        "--no-cache",
    ])
    assert exit_code == 0

    # 2. Test --clear-cache
    exit_code_clear = main([
        "lint",
        "--project", str(tmp_path),
        "--provider", "dbt",
        "--clear-cache",
    ])
    assert exit_code_clear == 0
    captured = capsys.readouterr()
    assert "Cleared" in captured.out

    # 3. Test health with --workers and --no-cache
    exit_code_health = main([
        "health",
        "--project", str(tmp_path),
        "--provider", "dbt",
        "--workers", "2",
        "--no-cache",
    ])
    assert exit_code_health == 0

    # 4. Test health with --clear-cache
    exit_code_health_clear = main([
        "health",
        "--project", str(tmp_path),
        "--provider", "dbt",
        "--clear-cache",
    ])
    assert exit_code_health_clear == 0

    # 5. Test main when TFF_NO_CACHE is already set in os.environ (verifies restoration)
    monkeypatch.setenv("TFF_NO_CACHE", "1")
    exit_code_env = main(["help"])
    assert exit_code_env == 0
    assert os.environ.get("TFF_NO_CACHE") == "1"
    monkeypatch.delenv("TFF_NO_CACHE")

    # 6. Test with config containing cache_ast: false
    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text("cache_ast: false\n", encoding="utf-8")
    exit_code_config_no_cache = main([
        "lint",
        "--project", str(tmp_path),
        "--provider", "dbt",
    ])
    assert exit_code_config_no_cache == 0


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_cli_debug_flag_root(mock_render, mock_load_config, mock_get_runner, tmp_path: Path):
    import logging

    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 1, ["rules"])
    mock_get_runner.return_value = mock_runner
    mock_render.return_value = True

    exit_code = main(["--debug", "lint", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_cli_debug_flag_subcommand(mock_render, mock_load_config, mock_get_runner, tmp_path: Path):
    import logging

    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 1, ["rules"])
    mock_get_runner.return_value = mock_runner
    mock_render.return_value = True

    exit_code = main(["lint", "--debug", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_cli_debug_flag_health(mock_render_health, mock_load_config, mock_get_runner, tmp_path: Path):
    import logging

    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 1, ["rules"])
    mock_get_runner.return_value = mock_runner

    exit_code = main(["health", "--debug", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


def test_cli_debug_only():
    import logging

    exit_code = main(["--debug"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


def test_cli_debug_env_var(monkeypatch):
    import logging

    monkeypatch.setenv("TFF_DEBUG", "1")
    exit_code = main(["help"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.core.cli._get_runner")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_cli_debug_captures_logs(mock_render, mock_load_config, mock_get_runner, tmp_path: Path, capsys):
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 2, ["rules"])
    mock_get_runner.return_value = mock_runner
    mock_render.return_value = True

    exit_code = main(["--debug", "lint", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "tff v" in captured.err
    assert "Check execution completed" in captured.err


@patch("tff.dbt.cli.run_all_checks")
@patch("tff.dbt.cli.load_fitness_config")
@patch("tff.dbt.cli.render_lint_report")
def test_deprecated_dbt_cli_debug(mock_render, mock_load_config, mock_run_checks, tmp_path: Path):
    import logging
    import tff.dbt.cli

    mock_run_checks.return_value = ([], 1, ["rules"])
    mock_render.return_value = True

    exit_code = tff.dbt.cli.main(["lint", "--debug", "--project", str(tmp_path)])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.dataform.cli.run_all_checks")
@patch("tff.dataform.cli.load_fitness_config")
@patch("tff.dataform.cli.render_lint_report")
def test_deprecated_dataform_cli_debug(mock_render, mock_load_config, mock_run_checks, tmp_path: Path):
    import logging
    import tff.dataform.cli

    mock_run_checks.return_value = ([], 1, ["rules"])
    mock_render.return_value = True

    exit_code = tff.dataform.cli.main(["lint", "--debug", "--project", str(tmp_path)])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.sqlmesh.cli.run_all_checks")
@patch("tff.sqlmesh.cli.load_fitness_config")
@patch("tff.sqlmesh.cli.render_lint_report")
def test_deprecated_sqlmesh_cli_debug(mock_render, mock_load_config, mock_run_checks, tmp_path: Path):
    import logging
    import tff.sqlmesh.cli

    mock_run_checks.return_value = ([], 1, ["rules"])
    mock_render.return_value = True

    exit_code = tff.sqlmesh.cli.main(["lint", "--debug", "--project", str(tmp_path)])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.core.cli._get_adapter")
def test_cli_get_adapter_error(mock_get_adapter, tmp_path: Path):
    mock_get_adapter.side_effect = ImportError("Adapter missing")
    exit_code = main(["lint", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 1


def test_cli_multi_project_lint(tmp_path: Path):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    (r1 / "config.py").touch()
    (r2 / "config.yaml").touch()

    mock_adapter = MagicMock()
    mock_adapter.provider_name = "sqlmesh"
    mock_adapter.run_checks.return_value = ([], 10, ["sqlmesh"])

    with (
        patch("tff.core.cli._get_adapter", return_value=mock_adapter),
        patch("tff.core.cli.load_fitness_config", return_value=MagicMock()),
        patch("tff.core.cli.render_lint_report", return_value=True),
    ):
        exit_code = main(["lint", "-p", str(r1), "-p", str(r2)])
        assert exit_code == 0
        mock_adapter.run_checks.assert_called_once()
        _, kwargs = mock_adapter.run_checks.call_args
        assert kwargs["project_root"] == [r1.resolve(), r2.resolve()]


def test_cli_multi_project_conflicting_providers(tmp_path: Path, capsys):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    (r1 / "config.py").touch()
    (r2 / "dbt_project.yml").touch()

    exit_code = main(["lint", "-p", str(r1), "-p", str(r2)])
    assert exit_code == 1
    captured = capsys.readouterr()
    assert "Conflicting pipeline engine providers" in captured.err


def test_cli_multi_project_health(tmp_path: Path):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    (r1 / "config.py").touch()
    (r2 / "config.yaml").touch()

    mock_adapter = MagicMock()
    mock_adapter.provider_name = "sqlmesh"
    mock_adapter.run_checks.return_value = ([], 10, ["sqlmesh"])

    with (
        patch("tff.core.cli._get_adapter", return_value=mock_adapter),
        patch("tff.core.cli.load_fitness_config", return_value=MagicMock()),
        patch("tff.core.health.calculate_health_scores", return_value=MagicMock()),
        patch("tff.core.health.render_health_report"),
    ):
        exit_code = main(["health", "-p", str(r1), "-p", str(r2), "--no-log"])
        assert exit_code == 0
        mock_adapter.run_checks.assert_called_once()
        _, kwargs = mock_adapter.run_checks.call_args
        assert kwargs["project_root"] == [r1.resolve(), r2.resolve()]


def test_cli_multi_project_info(tmp_path: Path, capsys):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    (r1 / "config.py").touch()
    (r2 / "settings.yaml").touch()

    exit_code = main(["info", "-p", str(r1), "-p", str(r2), "--provider", "sqlmesh"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "[repo1] config.py" in captured.out
    assert "[repo2] settings.yaml" in captured.out


def test_cli_project_list_attribute(tmp_path: Path):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    (r1 / "config.py").touch()
    (r2 / "config.py").touch()

    with patch("argparse.ArgumentParser.parse_args") as mock_parse_args:
        mock_args = MagicMock()
        mock_args.command = "lint"
        mock_args.projects = None
        mock_args.project = [r1, r2]
        mock_args.provider = "sqlmesh"
        mock_args.config = "fitness_functions.yaml"
        mock_args.checks = None
        mock_args.dialect = None
        mock_args.fix = False
        mock_args.json = False
        mock_args.format = "text"
        mock_args.fail_level = "error"
        mock_args.group_by = "model"
        mock_args.github_annotations = False
        mock_args.junit_xml = None
        mock_args.no_log = True
        mock_parse_args.return_value = mock_args

        mock_adapter = MagicMock()
        mock_adapter.provider_name = "sqlmesh"
        mock_adapter.run_checks.return_value = ([], 1, ["sqlmesh"])

        with (
            patch("tff.core.cli._get_adapter", return_value=mock_adapter),
            patch("tff.core.cli.load_fitness_config", return_value=MagicMock()),
            patch("tff.core.cli.render_lint_report", return_value=True),
        ):
            exit_code = main([])
            assert exit_code == 0
            mock_adapter.run_checks.assert_called_once()
            _, kwargs = mock_adapter.run_checks.call_args
            assert kwargs["project_root"] == [r1.resolve(), r2.resolve()]


def test_cli_multi_project_stats(tmp_path: Path, capsys):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    (r1 / ".tff_logs" / "health").mkdir(parents=True)
    (r2 / ".tff_logs" / "health").mkdir(parents=True)

    from datetime import datetime
    import json
    today = datetime.now()
    with open(r1 / ".tff_logs" / "health" / "h1.log", "w", encoding="utf-8") as f:
        json.dump({"timestamp": today.astimezone().isoformat(), "overall_score": 90.0, "models_checked": 10}, f)
    with open(r2 / ".tff_logs" / "health" / "h2.log", "w", encoding="utf-8") as f:
        json.dump({"timestamp": today.astimezone().isoformat(), "overall_score": 80.0, "models_checked": 10}, f)

    # 1. Text / ASCII output
    exit_code = main(["stats", "-p", str(r1), "-p", str(r2)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "tff Project Health Score Trend" in captured.out
    assert "85.0%" in captured.out

    # 2. JSON output with project_roots
    exit_code_json = main(["stats", "-p", str(r1), "-p", str(r2), "--json"])
    assert exit_code_json == 0
    captured_json = capsys.readouterr()
    data = json.loads(captured_json.out)
    assert data["project_root"] == str(r1.resolve())
    assert data["project_roots"] == [str(r1.resolve()), str(r2.resolve())]
    assert data["history"][-1]["health_score"] == 85.0


def test_cli_check_alias(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    with patch("tff.core.cli.get_adapter") as mock_get_adapter:
        mock_adapter = MagicMock()
        mock_adapter.provider_name = "dbt"
        mock_adapter.run_checks.return_value = ([], 0, [])
        mock_get_adapter.return_value = mock_adapter

        with patch("tff.core.cli.render_lint_report", return_value=True):
            exit_code = main(["check", "--project", str(tmp_path)])
            assert exit_code == 0
            mock_adapter.run_checks.assert_called_once()


def test_mask_sensitive_args_separate_values():
    raw_args = ["action", "--github-token", "ghp_secret_token_123", "--diff-against-base"]
    expected = ["action", "--github-token", "***", "--diff-against-base"]
    assert mask_sensitive_args(raw_args) == expected


def test_mask_sensitive_args_equals_values():
    raw_args = ["action", "--github-token=ghp_secret_token_123", "--diff-against-base"]
    expected = ["action", "--github-token=***", "--diff-against-base"]
    assert mask_sensitive_args(raw_args) == expected


def test_mask_sensitive_args_case_and_underscores():
    raw_args = [
        "--GITHUB-TOKEN=secret1",
        "--github_token",
        "secret2",
        "--api-key",
        "key123",
        "--api_key=key456",
        "--password",
        "pass1",
        "--secret=sec1",
    ]
    expected = [
        "--GITHUB-TOKEN=***",
        "--github_token",
        "***",
        "--api-key",
        "***",
        "--api_key=***",
        "--password",
        "***",
        "--secret=***",
    ]
    assert mask_sensitive_args(raw_args) == expected


def test_mask_sensitive_args_suffix_matching():
    raw_args = [
        "--my-custom-token",
        "custom_tok",
        "--db-password=pass",
        "--oauth-client-secret",
        "oauth_sec",
    ]
    expected = [
        "--my-custom-token",
        "***",
        "--db-password=***",
        "--oauth-client-secret",
        "***",
    ]
    assert mask_sensitive_args(raw_args) == expected


def test_mask_sensitive_args_access_keys_and_webhooks():
    raw_args = [
        "--access-key",
        "AKIAIOSFODNN7EXAMPLE",
        "--private-key=my_private_key_content",
        "--aws-access-key",
        "secret_aws_key",
        "--ssh-private-key=ssh_key_secret",
        "--webhook-secret",
        "whsec_abc123",
        "--slack-webhook-url=https://hooks.slack.com/services/T00/B00/X00",
        "--github-webhook-secret",
        "gh_hook_sec",
        "--webhook-url",
        "https://example.com/webhook",
    ]
    expected = [
        "--access-key",
        "***",
        "--private-key=***",
        "--aws-access-key",
        "***",
        "--ssh-private-key=***",
        "--webhook-secret",
        "***",
        "--slack-webhook-url=***",
        "--github-webhook-secret",
        "***",
        "--webhook-url",
        "***",
    ]
    assert mask_sensitive_args(raw_args) == expected


def test_mask_sensitive_args_non_sensitive_args():
    raw_args = [
        "lint",
        "--project",
        "/path/to/project",
        "--config=fitness_functions.yaml",
        "--key-column",
        "user_id",
        "--primary-key=id",
        "name=value",
    ]
    assert mask_sensitive_args(raw_args) == raw_args


def test_mask_sensitive_args_custom_flags():
    raw_args = ["--internal-cred", "secret_val", "--normal-flag", "normal_val"]
    masked = mask_sensitive_args(raw_args, sensitive_flags=frozenset({"--internal-cred"}))
    assert masked == ["--internal-cred", "***", "--normal-flag", "normal_val"]


def test_mask_sensitive_args_edge_cases():
    assert mask_sensitive_args([]) == []
    # Trailing sensitive flag without value
    assert mask_sensitive_args(["--github-token"]) == ["--github-token"]
    # Consecutive sensitive flags
    raw_args = ["--token", "tok", "--password", "pass"]
    assert mask_sensitive_args(raw_args) == ["--token", "***", "--password", "***"]


def test_cli_debug_logging_masks_github_token(capsys):
    secret = "ghp_super_secret_token_12345"
    with patch("tff.core.action.execute_action", return_value=0):
        exit_code = main(["--debug", "action", "--github-token", secret])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert secret not in captured.err
    assert "'--github-token', '***'" in captured.err


def test_cli_debug_logging_masks_github_token_equals(capsys):
    secret = "ghp_super_secret_token_67890"
    with patch("tff.core.action.execute_action", return_value=0):
        exit_code = main(["--debug", "action", f"--github-token={secret}"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert secret not in captured.err
    assert "'--github-token=***'" in captured.err


def test_cli_lint_interactive_spinner(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 3, ["rules"])

    with patch("tff.core.cli._get_runner", return_value=mock_runner), \
         patch("sys.stderr.isatty", return_value=True), \
         patch.dict(os.environ, {"TERM": "xterm-256color", "CI": ""}, clear=False), \
         patch("tff.core.cli.render_lint_report", return_value=True) as mock_render:
        exit_code = main(["lint", "--project", str(tmp_path)])
        assert exit_code == 0
        assert mock_render.call_count == 1
        call_kwargs = mock_render.call_args[1]
        assert call_kwargs["duration"] is not None


def test_cli_lint_autofix_interactive_spinner(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding

    finding = LintFinding(
        check="nomissingowner",
        severity="error",
        message="Missing owner",
        model="user_model",
        path="models/marts/user_model.sql",
    )
    model = ModelRepresentation(
        name="user_model",
        path=str(tmp_path / "models/marts/user_model.sql"),
        dialect="duckdb",
        is_symbolic=False,
        is_external=False,
        columns_to_types={},
        depends_on=set(),
        description=None,
        owner=None,
        grains=[],
        audits=[],
        materialized="table",
        expression=None,
        tags=[],
        meta={},
        provider="dbt",
    )

    mock_adapter = MagicMock()
    mock_adapter.provider_name = "dbt"
    # First run returns finding, second run returns clean
    mock_adapter.run_checks.side_effect = [
        ([finding], 1, ["nomissingowner"]),
        ([], 1, ["nomissingowner"]),
    ]
    mock_adapter.load_models.return_value = {"user_model": model}
    mock_adapter.apply_metadata_fix.return_value = "Fixed owner"

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli._detect_provider", return_value="dbt"), \
         patch("sys.stderr.isatty", return_value=True), \
         patch.dict(os.environ, {"TERM": "xterm-256color", "CI": ""}, clear=False), \
         patch("tff.core.autofix.apply_autofixes", return_value=["Fixed owner"]), \
         patch("tff.core.cli.render_lint_report", return_value=True) as mock_render:
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 0
        assert mock_adapter.run_checks.call_count == 2
        assert mock_render.call_count == 1
        assert mock_render.call_args[1]["duration"] is not None










