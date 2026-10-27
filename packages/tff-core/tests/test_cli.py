from conftest import _make_finding, _make_model
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tff.core.cli import (
    _detect_provider,
    _explain_single_check,
    _get_adapter,
    _render_rules_table,
    main,
    mask_sensitive_args,
)
from tff.core.registry import CheckDefinition


@pytest.mark.parametrize(
    "marker,is_dir,content,expected",
    [
        ("dbt_project.yml", False, "", "dbt"),
        ("config.py", False, "from sqlmesh.core.config import Config\nconfig = Config()", "sqlmesh"),
        ("config.yaml", False, "gateways:\n  local:\n    connection:\n      type: duckdb", "sqlmesh"),
        ("config.yml", False, "model_defaults:\n  dialect: duckdb", "sqlmesh"),
        ("sqlmesh.yaml", False, "", "sqlmesh"),
        ("sqlmesh.yml", False, "", "sqlmesh"),
        (".sqlmesh", True, "", "sqlmesh"),
    ],
)
def test_detect_provider_success(tmp_path: Path, marker: str, is_dir: bool, content: str, expected: str):
    if is_dir:
        (tmp_path / marker).mkdir()
    elif content:
        (tmp_path / marker).write_text(content)
    else:
        (tmp_path / marker).touch()
    assert _detect_provider(tmp_path) == expected


def test_detect_provider_conflict(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    (tmp_path / "config.py").write_text(
        "from sqlmesh.core.config import Config\nconfig = Config()"
    )
    with pytest.raises(
        ValueError, match="Both dbt and SQLMesh configuration files were detected"
    ):
        _detect_provider(tmp_path)


def test_detect_provider_not_found(tmp_path: Path):
    with pytest.raises(ValueError, match="Could not detect project type"):
        _detect_provider(tmp_path)


@pytest.mark.parametrize(
    "provider,expected_module,adapter_cls",
    [
        ("dbt", "tff.dbt.adapter", "DBTAdapter"),
        ("sqlmesh", "tff.sqlmesh.adapter", "SQLMeshAdapter"),
    ],
)
def test_get_runner_success(provider: str, expected_module: str, adapter_cls: str):
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_import.return_value = mock_module
        adapter = _get_adapter(provider)
        mock_import.assert_called_once_with(expected_module)
        assert adapter == getattr(mock_module, adapter_cls).return_value


@pytest.mark.parametrize(
    "provider,err_match",
    [
        ("dbt", "tff is not installed with dbt support"),
        ("sqlmesh", "tff is not installed with sqlmesh support"),
    ],
)
def test_get_runner_import_error(provider: str, err_match: str):
    with patch(
        "importlib.import_module",
        side_effect=ImportError(f"No module named 'tff.{provider}.adapter'"),
    ):
        with pytest.raises(ImportError, match=err_match):
            _get_adapter(provider)


def test_get_runner_unknown():
    with pytest.raises(ValueError, match="Unknown provider"):
        _get_adapter("unknown_provider")


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_dbt(
    mock_render,
    mock_load_config,
    mock_get_adapter,
    mock_detect_provider,
    tmp_path: Path,
):
    mock_detect_provider.return_value = "dbt"
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 5, ["rules"])
    mock_get_adapter.return_value = mock_adapter
    mock_render.return_value = True

    # Run the main cli
    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--dialect", "duckdb"])

    assert exit_code == 0
    mock_detect_provider.assert_called_once()
    mock_get_adapter.assert_called_once_with("dbt")
    mock_adapter.run_checks.assert_called_once_with(
        project_root=[tmp_path.resolve()],
        config=mock_load_config.return_value,
        checks=None,
        dialect="duckdb",
        manifest_path=None,
    )
    assert mock_render.call_count == 1
    call_args, call_kwargs = mock_render.call_args
    assert call_args == ([],)
    assert call_kwargs["models_checked"] == 5
    assert call_kwargs["executed_checks"] == ["rules"]
    assert call_kwargs["fail_level"] == "error"
    assert call_kwargs["group_by"] == "model"
    assert call_kwargs["duration"] is not None


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_sqlmesh_explicit_provider(
    mock_render,
    mock_load_config,
    mock_get_adapter,
    tmp_path: Path,
):
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 10, ["sqlmesh"])
    mock_get_adapter.return_value = mock_adapter
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
    mock_get_adapter.assert_called_once_with("sqlmesh")
    mock_adapter.run_checks.assert_called_once_with(
        project_root=[tmp_path.resolve()],
        config=mock_load_config.return_value,
        checks=["sqlmesh", "layer_integrity"],
        dialect=None,
        manifest_path=None,
    )


@patch("tff.core.cli._detect_provider")
def test_main_lint_detect_failure(mock_detect_provider, tmp_path: Path):
    mock_detect_provider.side_effect = ValueError("No project found")

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str])
    assert exit_code == 1


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_adapter")
def test_main_lint_import_error_exit(
    mock_get_adapter, mock_detect_provider, tmp_path: Path
):
    mock_detect_provider.return_value = "dbt"
    mock_get_adapter.side_effect = ImportError("Not installed")

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str])
    assert exit_code == 1


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
def test_main_lint_load_config_error(mock_load_config, mock_get_adapter, tmp_path: Path):
    mock_load_config.side_effect = Exception("Config load failed")
    mock_adapter = MagicMock()
    mock_get_adapter.return_value = mock_adapter

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--provider", "dbt"])
    assert exit_code == 1


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_sqlmesh_dialect_warning(
    mock_render, mock_load_config, mock_get_adapter, tmp_path: Path
):
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 0, [])
    mock_get_adapter.return_value = mock_adapter
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


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
def test_main_lint_run_checks_error(mock_load_config, mock_get_adapter, tmp_path: Path):
    mock_adapter = MagicMock()
    mock_adapter.run_checks.side_effect = Exception("Check execution failed")
    mock_get_adapter.return_value = mock_adapter

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--provider", "dbt"])
    assert exit_code == 1


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_group_by_connascence(
    mock_render, mock_load_config, mock_get_adapter, tmp_path: Path
):
    """Test that --group-by connascence is forwarded to render_lint_report."""
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 5, ["rules"])
    mock_get_adapter.return_value = mock_adapter
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
        mock_module = MagicMock()
        mock_adapter = MagicMock()
        mock_adapter.run_checks.return_value = ([], 0, [])
        mock_module.DBTAdapter.return_value = mock_adapter
        mock_import.return_value = mock_module
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

        mock_import.assert_any_call("tff.dbt.adapter")
        mock_adapter.run_checks.assert_called_once()


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

    # Test tff help explain
    assert main(["help", "explain"]) == 0
    captured = capsys.readouterr()
    assert "Explain a fitness check" in captured.out

    # Test tff help rules
    assert main(["help", "rules"]) == 0
    captured = capsys.readouterr()
    assert "List all available fitness checks" in captured.out


def test_invalid_command_error_hint(capsys):
    # Test tff foo
    with pytest.raises(SystemExit) as excinfo:
        main(["foo"])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "invalid choice: 'foo'" in captured.err
    assert "For help, try 'tff --help'" in captured.err


@pytest.mark.parametrize(
    "argv,expected_out_snippets,expected_err_snippets,expected_exit",
    [
        ([], ["Run Transformation Fitness Function (tff) checks", "tff"], [], 0),
        (["help", "info"], ["Show configuration and environment information", "--provider"], [], 0),
        (["explain", "CoA"], ["duplicate_ctes (Connascence of Algorithm (CoA))"], [], 0),
        (["explain", "CoV"], ["connascence_of_value (Connascence of Value (CoV))"], [], 0),
        (["explain", "duplicate_cte"], ["duplicate_ctes (Connascence of Algorithm (CoA))"], [], 0),
        (["explain", "duplcate_ctes"], [], ["Unknown check or category 'duplcate_ctes'", "Did you mean 'duplicate_ctes'?"], 1),
        (["explain", "xyzzy"], [], ["Unknown check or category 'xyzzy'"], 1),
    ],
)
def test_cli_direct_return_commands(
    argv: list[str],
    expected_out_snippets: list[str],
    expected_err_snippets: list[str],
    expected_exit: int,
    capsys,
):
    assert main(argv) == expected_exit
    captured = capsys.readouterr()
    for snippet in expected_out_snippets:
        assert snippet in captured.out
    for snippet in expected_err_snippets:
        assert snippet in captured.err
    if argv == ["explain", "xyzzy"]:
        assert "Did you mean" not in captured.err


@pytest.mark.parametrize("flag", ["--version", "-v"])
def test_version_flags(flag: str, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([flag])
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
        assert "tff version:" in captured.out
        assert "Provider:" in captured.out
        assert "dbt" in captured.out
        assert "fitness_functions.yaml" in captured.out
        assert "Contract groups:" in captured.out
        assert "Exclusions:" in captured.out
        assert "Adapter Versions" not in captured.out
        assert "Provider Files" in captured.out
        assert "dbt_project.yml" in captured.out
        assert "manifest.json" in captured.out

        exit_code_all = main(
            [
                "info",
                "--project",
                str(tmp_path),
                "--config",
                "fitness_functions.yaml",
                "--all-adapters",
            ]
        )
        assert exit_code_all == 0
        captured_all = capsys.readouterr()
        assert "Adapter Versions" in captured_all.out
        assert "dbt integration" in captured_all.out


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

    # Verify that the versions from the simulated virtualenv are displayed in tff version
    assert "tff version:" in captured.out
    assert "1.2.3" in captured.out
    assert "Adapter Versions" not in captured.out

    # Verify that --all-adapters displays the adapter table with virtualenv versions
    exit_code_all = main(
        ["info", "--project", str(tmp_path), "--provider", "sqlmesh", "--all-adapters"]
    )
    assert exit_code_all == 0
    captured_all = capsys.readouterr()
    assert "Adapter Versions" in captured_all.out
    assert "1.2.3" in captured_all.out
    assert "sqlmesh integration" in captured_all.out
    assert "dbt integration" in captured_all.out


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_json(
    mock_render,
    mock_load_config,
    mock_get_adapter,
    mock_detect_provider,
    tmp_path: Path,
    capsys,
):
    mock_detect_provider.return_value = "dbt"
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 5, ["rules"])
    mock_get_adapter.return_value = mock_adapter

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
@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_main_lint_no_log(
    mock_render,
    mock_load_config,
    mock_get_adapter,
    mock_detect_provider,
    tmp_path: Path,
):
    mock_detect_provider.return_value = "dbt"
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 5, ["rules"])
    mock_get_adapter.return_value = mock_adapter

    project_str = str(tmp_path)
    exit_code = main(["lint", "--project", project_str, "--no-log"])

    assert exit_code == 0
    assert not (tmp_path / ".tff_logs").exists()


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_main_health_normal_and_json(
    mock_render_health,
    mock_load_config,
    mock_get_adapter,
    mock_detect_provider,
    tmp_path: Path,
    capsys,
):
    mock_detect_provider.return_value = "dbt"
    mock_adapter = MagicMock()
    # health command expects findings, models_checked, executed_checks
    mock_adapter.run_checks.return_value = ([], 8, ["rules"])
    mock_get_adapter.return_value = mock_adapter

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
@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_main_health_no_log(
    mock_render_health,
    mock_load_config,
    mock_get_adapter,
    mock_detect_provider,
    tmp_path: Path,
):
    mock_detect_provider.return_value = "dbt"
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 8, ["rules"])
    mock_get_adapter.return_value = mock_adapter

    project_str = str(tmp_path)
    exit_code = main(["health", "--project", project_str, "--no-log"])
    assert exit_code == 0
    assert not (tmp_path / ".tff_logs").exists()


@patch("tff.core.cli._detect_provider")
@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_main_health_with_scope(
    mock_render_health,
    mock_load_config,
    mock_get_adapter,
    mock_detect_provider,
    tmp_path: Path,
    capsys,
):
    mock_detect_provider.return_value = "dbt"
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 8, ["rules"])
    mock_get_adapter.return_value = mock_adapter

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
        assert tff.core.cli.__version__ == "0.25.0"

    # Restore original by reloading again without patch
    import importlib
    import tff.core.cli

    importlib.reload(tff.core.cli)


def test_cli_main_lint_with_fix(tmp_path: Path):
    # Create workflow_settings.yaml to auto-detect provider as Dataform
    (tmp_path / "workflow_settings.yaml").touch()

    # Create a sqlx file containing mismatched name
    sql_file = tmp_path / "definitions/my_model.sqlx"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text('config {\n  name: "wrong_model"\n}\nSELECT 1', encoding="utf-8")

    # Mock adapter run_checks to return initial findings
    mock_adapter = MagicMock()
    mock_adapter.provider_name = "dataform"
    # 1st call returns finding, 2nd call (re-run) returns empty findings
    mock_adapter.run_checks.side_effect = [
        (
            [
                _make_finding(
                    check="filename_equals_modelname",
                    severity="error",
                    model="wrong_model",
                    path="definitions/my_model.sqlx",
                    message="Model name does not match file stem."
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
    mock_adapter.load_models.return_value = {
        "my_model": _make_model(
            name="my_model",
            path=str(sql_file),
            dialect="bigquery"
        )
    }

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config, \
         patch("tff.core.cli.render_lint_report", return_value=True):
        
        mock_load_config.return_value = MagicMock()
        
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        
        assert exit_code == 0
        # Verify file was updated
        assert 'name: "my_model"' in sql_file.read_text(encoding="utf-8")
        assert mock_adapter.run_checks.call_count == 2


def test_cli_main_lint_with_fix_sqlmesh(tmp_path: Path):
    
    # Create config.py to auto-detect provider as SQLMesh
    (tmp_path / "config.py").write_text(
        "from sqlmesh.core.config import Config\nconfig = Config()"
    )
    
    # Create a SQL file
    sql_file = tmp_path / "models/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("MODEL (\n  name wrong_model\n);\nSELECT 1", encoding="utf-8")
    
    # Mock adapter
    mock_adapter = MagicMock()
    mock_adapter.provider_name = "sqlmesh"
    mock_adapter.run_checks.side_effect = [
        (
            [
                _make_finding(
                    check="filenameequalsmodelname",
                    severity="error",
                    model="wrong_model",
                    path="models/my_model.sql",
                    message="Model name does not match file stem."
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
    mock_adapter.load_models.return_value = {
        "my_model": _make_model(
            name="my_model",
            path=str(sql_file),
            dialect="ansi"
        )
    }
    
    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config, \
         patch("tff.core.cli.render_lint_report", return_value=True):
        
        mock_load_config.return_value = MagicMock()
        
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 0
        assert "name my_model" in sql_file.read_text(encoding="utf-8")
        assert mock_adapter.run_checks.call_count == 2


def test_cli_main_lint_with_fix_load_models_exception(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    
    mock_adapter = MagicMock()
    mock_adapter.provider_name = "dbt"
    mock_adapter.run_checks.return_value = (
        [
            _make_finding(
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
    mock_adapter.load_models.side_effect = Exception("Load failed")
    
    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config, \
         patch("tff.core.cli.render_lint_report", return_value=False):
        
        mock_load_config.return_value = MagicMock()
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 1  # Should fail since it wasn't fixed and returned a finding
        assert mock_adapter.run_checks.call_count == 1  # No re-run


def test_cli_main_lint_with_fix_rerun_exception(tmp_path: Path):
    (tmp_path / "config.py").write_text("from sqlmesh.core.config import Config\nconfig = Config()")
    
    sql_file = tmp_path / "models/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("MODEL (\n  name wrong_model\n);\nSELECT 1", encoding="utf-8")
    
    mock_adapter = MagicMock()
    mock_adapter.provider_name = "sqlmesh"
    mock_adapter.run_checks.side_effect = [
        (
            [
                _make_finding(
                    check="filenameequalsmodelname",
                    severity="error",
                    model="wrong_model",
                    path="models/my_model.sql",
                    message="Model name mismatch"
                )
            ],
            1,
            ["sqlmesh"]
        ),
        Exception("Re-run failed")
    ]
    mock_adapter.load_models.return_value = {
        "my_model": _make_model(
            name="my_model",
            path=str(sql_file),
            dialect="ansi"
        )
    }
    
    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.load_fitness_config") as mock_load_config:
        
        mock_load_config.return_value = MagicMock()
        
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 1
        assert mock_adapter.run_checks.call_count == 2


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


@pytest.mark.parametrize(
    "cmd,has_config,is_json,expect_notice",
    [
        ("lint", False, False, True),
        ("lint", True, False, False),
        ("lint", False, True, False),
        ("health", False, False, True),
        ("health", True, False, False),
    ],
)
def test_cli_config_notice(
    tmp_path: Path, capsys, cmd: str, has_config: bool, is_json: bool, expect_notice: bool
):
    (tmp_path / "dbt_project.yml").touch()
    if has_config:
        (tmp_path / "fitness_functions.yaml").write_text(
            "layers:\n  order: [staging, marts]\n", encoding="utf-8"
        )
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 0, [])

    args = [cmd, "--project", str(tmp_path)]
    if is_json:
        args.append("--json")

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.health.render_health_report"):
        exit_code = main(args)
        assert exit_code == 0
        captured = capsys.readouterr()
        if expect_notice:
            assert "Notice: No fitness_functions.yaml found." in captured.err
            assert "Run 'tff init' to generate a project configuration file." in captured.err
        else:
            assert "Notice: No fitness_functions.yaml found." not in captured.err
            assert "Notice: No fitness_functions.yaml found." not in captured.out


def test_cli_lint_format_sarif(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()

    finding = _make_finding(
        check="banselectstar",
        severity="error",
        message="SELECT * not allowed",
        model="model_a",
        path="models/model_a.sql",
        line=10,
    )
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "sarif"])
        assert exit_code == 1
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        assert len(data["runs"][0]["results"]) == 1
        assert data["runs"][0]["results"][0]["ruleId"] == "banselectstar"


def test_cli_lint_format_json(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 1, [])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["command"] == "lint"
        assert data["passed"] is True


def test_cli_lint_format_text(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 1, [])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.render_lint_report", return_value=True) as mock_render:
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "text"])
        assert exit_code == 0
        mock_render.assert_called_once()


def test_cli_lint_github_annotations_flag(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()

    finding = _make_finding(
        check="nomissingowner",
        severity="warning",
        message="Missing model owner",
        model="stg_users",
        path="models/staging/stg_users.sql",
        line=1,
    )
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([finding], 1, ["nomissingowner"])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.render_lint_report", return_value=True):
        exit_code = main(["lint", "--project", str(tmp_path), "--github-annotations"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert (
            "::warning file=models/staging/stg_users.sql,line=1,title=WRN · Missing owner (Quality & Metadata)::* Missing model owner (https://tff.readthedocs.io/en/latest/rules_and_checks/#metadata-metadata)"
            in captured.out
        )


def test_cli_lint_github_actions_env(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tmp_path / "dbt_project.yml").touch()

    finding = _make_finding(
        check="banselectstar",
        severity="error",
        message="SELECT * forbidden",
        model="fct_orders",
        path="models/marts/fct_orders.sql",
        line=25,
    )
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.render_lint_report", return_value=False):
        exit_code = main(["lint", "--project", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "::error file=models/marts/fct_orders.sql,line=25,title=ERR · No SELECT * (Connascence of Name)::! SELECT * forbidden" in captured.out


def test_cli_lint_github_actions_env_sarif_no_annotations(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    (tmp_path / "dbt_project.yml").touch()

    finding = _make_finding(
        check="banselectstar",
        severity="error",
        message="SELECT * forbidden",
        model="fct_orders",
        path="models/marts/fct_orders.sql",
        line=25,
    )
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "sarif"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "::error" not in captured.out
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"


def test_cli_lint_junit_xml(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 2, [])
    junit_target = tmp_path / "reports" / "junit.xml"

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
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

    finding = _make_finding(
        check="banselectstar",
        severity="error",
        message="SELECT * not permitted in marts",
        model="fct_orders",
        path="models/marts/fct_orders.sql",
        line=12,
    )
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([finding], 1, ["banselectstar"])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "github"])
        assert exit_code == 1
        captured = capsys.readouterr()
        # Only pure workflow command annotations in stdout, no rich summary table
        assert (
            captured.out.strip()
            == "::error file=models/marts/fct_orders.sql,line=12,title=ERR · No SELECT * (Connascence of Name)::! SELECT * not permitted in marts (https://tff.readthedocs.io/en/latest/rules_and_checks/#ban-select-ban_select_star)"
        )
        assert "LINT FAILED" not in captured.out


def test_cli_lint_format_github_empty(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 5, [])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter):
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "github"])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert captured.out == ""


def test_cli_lint_structured_with_github_annotations(tmp_path: Path, capsys):
    (tmp_path / "dbt_project.yml").touch()

    finding = _make_finding(
        check="nomissingowner",
        severity="warning",
        message="Missing owner attribute",
        model="stg_customers",
        path="models/staging/stg_customers.sql",
        line=1,
    )
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([finding], 1, ["nomissingowner"])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter):
        # 1. SARIF with --github-annotations
        exit_code = main(["lint", "--project", str(tmp_path), "--format", "sarif", "--github-annotations"])
        assert exit_code == 0
        captured = capsys.readouterr()
        # stdout is pure, parseable SARIF JSON
        data = json.loads(captured.out)
        assert data["version"] == "2.1.0"
        # annotations routed to stderr to prevent corrupting stdout
        assert (
            "::warning file=models/staging/stg_customers.sql,line=1,title=WRN · Missing owner (Quality & Metadata)::* Missing owner attribute (https://tff.readthedocs.io/en/latest/rules_and_checks/#metadata-metadata)"
            in captured.err
        )

        # 2. JSON with --github-annotations
        exit_code_json = main(["lint", "--project", str(tmp_path), "--format", "json", "--github-annotations"])
        assert exit_code_json == 0
        captured_json = capsys.readouterr()
        # stdout is pure, parseable JSON
        data_json = json.loads(captured_json.out)
        assert data_json["command"] == "lint"
        assert (
            "::warning file=models/staging/stg_customers.sql,line=1,title=WRN · Missing owner (Quality & Metadata)::* Missing owner attribute (https://tff.readthedocs.io/en/latest/rules_and_checks/#metadata-metadata)"
            in captured_json.err
        )


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
        assert "my_custom_engine" in captured_info.out
        assert "Plugin:" in captured_info.out
        assert "custom_plugin.py" in captured_info.out
        assert "custom_config.yml" in captured_info.out

        # Test info command with --all-adapters
        exit_code_info_all = main([
            "info",
            "--project", str(tmp_path),
            "--provider", "my_custom_engine",
            "--all-adapters",
        ])
        assert exit_code_info_all == 0
        captured_info_all = capsys.readouterr()
        assert "my_custom_engine integration" in captured_info_all.out

        # 2. Test lint command with custom provider
        exit_code_lint = main([
            "lint",
            "--project", str(tmp_path),
            "--provider", "my_custom_engine",
        ])
        assert exit_code_lint == 0
        captured_lint = capsys.readouterr()
        assert "PASS — all fitness functions satisfied." in captured_lint.out
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


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_cli_debug_flag_root(mock_render, mock_load_config, mock_get_adapter, tmp_path: Path):
    import logging

    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 1, ["rules"])
    mock_get_adapter.return_value = mock_adapter
    mock_render.return_value = True

    exit_code = main(["--debug", "lint", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_cli_debug_flag_subcommand(mock_render, mock_load_config, mock_get_adapter, tmp_path: Path):
    import logging

    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 1, ["rules"])
    mock_get_adapter.return_value = mock_adapter
    mock_render.return_value = True

    exit_code = main(["lint", "--debug", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.health.render_health_report")
def test_cli_debug_flag_health(mock_render_health, mock_load_config, mock_get_adapter, tmp_path: Path):
    import logging

    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 1, ["rules"])
    mock_get_adapter.return_value = mock_adapter

    exit_code = main(["health", "--debug", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@pytest.mark.parametrize(
    "argv,use_env",
    [
        (["--debug"], False),
        (["help"], True),
    ],
)
def test_cli_debug_logging_modes(argv: list[str], use_env: bool, monkeypatch):
    import logging

    if use_env:
        monkeypatch.setenv("TFF_DEBUG", "1")
    exit_code = main(argv)
    assert exit_code == 0
    assert logging.getLogger().level == logging.DEBUG


@patch("tff.core.cli._get_adapter")
@patch("tff.core.cli.load_fitness_config")
@patch("tff.core.cli.render_lint_report")
def test_cli_debug_captures_logs(mock_render, mock_load_config, mock_get_adapter, tmp_path: Path, capsys):
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 2, ["rules"])
    mock_get_adapter.return_value = mock_adapter
    mock_render.return_value = True

    exit_code = main(["--debug", "lint", "--project", str(tmp_path), "--provider", "dbt"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "tff v" in captured.err
    assert "Check execution completed" in captured.err


@pytest.mark.parametrize(
    "cli_module_name",
    ["tff.dbt.cli", "tff.dataform.cli", "tff.sqlmesh.cli"],
)
def test_deprecated_provider_cli_debug(tmp_path: Path, cli_module_name: str):
    import importlib
    import logging

    cli_mod = importlib.import_module(cli_module_name)
    with patch(f"{cli_module_name}.run_all_checks", return_value=([], 1, ["rules"])), \
         patch(f"{cli_module_name}.load_fitness_config"), \
         patch(f"{cli_module_name}.render_lint_report", return_value=True):
        exit_code = cli_mod.main(["lint", "--debug", "--project", str(tmp_path)])
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
    (r1 / "config.py").write_text(
        "from sqlmesh.core.config import Config\nconfig = Config()"
    )
    (r2 / "config.yaml").write_text(
        "gateways:\n  local:\n    connection:\n      type: duckdb"
    )

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
    (r1 / "config.py").write_text(
        "from sqlmesh.core.config import Config\nconfig = Config()"
    )
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
    (r1 / "config.py").write_text(
        "from sqlmesh.core.config import Config\nconfig = Config()"
    )
    (r2 / "config.yaml").write_text(
        "gateways:\n  local:\n    connection:\n      type: duckdb"
    )

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
    (r1 / "config.py").write_text(
        "from sqlmesh.core.config import Config\nconfig = Config()"
    )
    (r2 / "config.py").write_text(
        "from sqlmesh.core.config import Config\nconfig = Config()"
    )

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


@pytest.mark.parametrize(
    "raw_args,expected",
    [
        (
            ["action", "--github-token", "ghp_secret_token_123", "--diff-against-base"],
            ["action", "--github-token", "***", "--diff-against-base"],
        ),
        (
            ["action", "--github-token=ghp_secret_token_123", "--diff-against-base"],
            ["action", "--github-token=***", "--diff-against-base"],
        ),
        (
            [
                "--GITHUB-TOKEN=secret1",
                "--github_token",
                "secret2",
                "--api-key",
                "key123",
                "--api_key=key456",
                "--password",
                "pass1",
                "--secret=sec1",
            ],
            [
                "--GITHUB-TOKEN=***",
                "--github_token",
                "***",
                "--api-key",
                "***",
                "--api_key=***",
                "--password",
                "***",
                "--secret=***",
            ],
        ),
        (
            [
                "--my-custom-token",
                "custom_tok",
                "--db-password=pass",
                "--oauth-client-secret",
                "oauth_sec",
            ],
            [
                "--my-custom-token",
                "***",
                "--db-password=***",
                "--oauth-client-secret",
                "***",
            ],
        ),
        (
            [
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
            ],
            [
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
            ],
        ),
        (
            [
                "lint",
                "--project",
                "/path/to/project",
                "--config=fitness_functions.yaml",
                "--key-column",
                "user_id",
                "--primary-key=id",
                "name=value",
            ],
            [
                "lint",
                "--project",
                "/path/to/project",
                "--config=fitness_functions.yaml",
                "--key-column",
                "user_id",
                "--primary-key=id",
                "name=value",
            ],
        ),
        ([], []),
        (["--github-token"], ["--github-token"]),
        (
            ["--token", "tok", "--password", "pass"],
            ["--token", "***", "--password", "***"],
        ),
    ],
)
def test_mask_sensitive_args(raw_args: list[str], expected: list[str]):
    assert mask_sensitive_args(raw_args) == expected


def test_mask_sensitive_args_custom_flags():
    raw_args = ["--internal-cred", "secret_val", "--normal-flag", "normal_val"]
    masked = mask_sensitive_args(raw_args, sensitive_flags=frozenset({"--internal-cred"}))
    assert masked == ["--internal-cred", "***", "--normal-flag", "normal_val"]


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
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 3, ["rules"])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
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

    finding = _make_finding(
        check="filenameequalsmodelname",
        severity="error",
        message="Filename does not match model name",
        model="user_model",
        path="models/marts/user_model.sql",
    )
    model = _make_model(
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
        ([finding], 1, ["filenameequalsmodelname"]),
        ([], 1, ["filenameequalsmodelname"]),
    ]
    mock_adapter.load_models.return_value = {"user_model": model}

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli._detect_provider", return_value="dbt"), \
         patch("sys.stderr.isatty", return_value=True), \
         patch.dict(os.environ, {"TERM": "xterm-256color", "CI": ""}, clear=False), \
         patch("tff.core.autofix.apply_autofixes", return_value=["Synchronized model name to 'user_model' in user_model.sql"]), \
         patch("tff.core.cli.render_lint_report", return_value=True) as mock_render:
        exit_code = main(["lint", "--project", str(tmp_path), "--fix"])
        assert exit_code == 0
        assert mock_adapter.run_checks.call_count == 2
        assert mock_render.call_count == 1
        assert mock_render.call_args[1]["duration"] is not None



@pytest.mark.parametrize(
    "typo,expected_suggestion",
    [
        ("lin", "lint"),
        ("chek", "check"),
        ("healt", "health"),
    ],
)
def test_fuzzy_typo_suggestions(typo: str, expected_suggestion: str, capsys):
    with pytest.raises(SystemExit) as excinfo:
        main([typo])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert f"Did you mean '{expected_suggestion}'?" in captured.err


def test_fuzzy_typo_no_suggestion_for_unrelated(capsys):
    """Completely unrelated command should not trigger a 'Did you mean' hint."""
    with pytest.raises(SystemExit) as excinfo:
        main(["xyzzy"])
    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert "Did you mean" not in captured.err


def test_cli_explain_single_check(capsys):
    assert main(["explain", "duplicate_ctes"]) == 0
    captured = capsys.readouterr()
    assert "duplicate_ctes (Connascence of Algorithm (CoA))" in captured.out
    assert "Severity:   Warning (Default)" in captured.out
    assert "Provider:   dbt, SQLMesh, Dataform" in captured.out
    assert "What it checks:" in captured.out
    assert "Why it matters:" in captured.out
    assert "How to fix:" in captured.out
    assert "Configuration (fitness_functions.yaml):" in captured.out
    assert "https://tff.readthedocs.io" in captured.out


def test_cli_explain_fixable_check(capsys):
    assert main(["explain", "filename_equals_modelname"]) == 0
    captured = capsys.readouterr()
    assert "Auto-fix:   Yes (run 'tff lint --fix')" in captured.out
    assert "Severity:   Error (Default)" in captured.out

    assert main(["explain", "no_positional_group_by_or_order_by"]) == 0
    captured_pos = capsys.readouterr()
    assert "Auto-fix:" not in captured_pos.out
    assert "no_positional_group_by_or_order_by" in captured_pos.out

    assert main(["explain", "no_positional_group_by"]) == 0
    captured_grp = capsys.readouterr()
    assert "Auto-fix:" not in captured_grp.out
    assert "no_positional_group_by" in captured_grp.out

    assert main(["explain", "no_positional_order_by"]) == 0
    captured_ord = capsys.readouterr()
    assert "Auto-fix:" not in captured_ord.out
    assert "no_positional_order_by" in captured_ord.out


def test_cli_explain_partial_substring_multi(capsys):
    # Partial substring 'select_star' matches ban_select_star and invalid_select_star_expansion
    assert main(["explain", "select_star"]) == 0
    captured = capsys.readouterr()
    assert "Matches for 'select_star'" in captured.out
    assert "ban_select_star" in captured.out
    assert "invalid_select_star_expansion" in captured.out


def test_cli_explain_all_and_no_args(capsys):
    # tff explain without args
    assert main(["explain"]) == 0
    captured = capsys.readouterr()
    assert "Available Fitness Checks & Rules" in captured.out
    assert "duplicate_ctes" in captured.out
    assert "ban_select_star" in captured.out

    # tff explain --all
    assert main(["explain", "--all"]) == 0
    captured2 = capsys.readouterr()
    assert "Available Fitness Checks & Rules" in captured2.out


def test_cli_rules_subcommand(capsys):
    # tff rules without args lists all checks
    assert main(["rules"]) == 0
    captured = capsys.readouterr()
    assert "Available Fitness Checks & Rules" in captured.out
    assert "duplicate_ctes" in captured.out

    # tff rules with check arg explains that check
    assert main(["rules", "duplicate_ctes"]) == 0
    captured2 = capsys.readouterr()
    assert "duplicate_ctes (Connascence of Algorithm (CoA))" in captured2.out


@pytest.mark.parametrize("arg", ["duplicate_ctes", "CoA", "duplicate_cte"])
def test_cli_explain_json_single_target(arg: str, capsys):
    import json

    assert main(["explain", arg, "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["id"] == "duplicate_ctes"
    assert data["category"] == "Connascence of Algorithm (CoA)"
    assert data["default_severity"] == "warning"
    assert "dbt" in data["providers"]
    assert len(data.get("what_it_checks", "")) > 0


def test_cli_explain_json_all(capsys):
    import json

    assert main(["explain", "--all", "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "checks" in data
    assert len(data["checks"]) >= 25


def test_cli_explain_json_category_multi(capsys):
    import json

    assert main(["explain", "CoN", "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["category"] == "Connascence of Name (CoN)"
    assert len(data["checks"]) >= 4


def test_cli_explain_json_substring_multi(capsys):
    import json

    assert main(["explain", "select_star", "--json"]) == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["query"] == "select_star"
    assert len(data["checks"]) == 2


def test_cli_explain_typo_json(capsys):
    import json

    assert main(["explain", "duplcate_ctes", "--json"]) == 1
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "Unknown check or category 'duplcate_ctes'" in data["error"]
    assert data["suggestion"] == "duplicate_ctes"


def test_explain_single_check_direct_call():
    c = CheckDefinition(
        id="custom_rule",
        label="Custom",
        category="Custom",
        scope="model",
        providers=("custom_engine",),
    )
    _explain_single_check(c)


def test_render_rules_table_direct_call():
    c = CheckDefinition(
        id="custom_rule",
        label="Custom",
        category="Custom",
        scope="model",
    )
    _render_rules_table([c])


def test_cli_lint_and_health_chunk_size_flag(tmp_path: Path):
    from unittest.mock import patch, MagicMock
    from tff.core.config import FitnessFunctionsConfig

    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 0, [])

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.load_fitness_config") as mock_load_cfg:
        cfg = FitnessFunctionsConfig()
        mock_load_cfg.return_value = cfg

        # 1. lint with --chunk-size
        exit_code = main([
            "lint",
            "--project", str(tmp_path),
            "--provider", "dbt",
            "--chunk-size", "10",
        ])
        assert exit_code == 0
        assert cfg.chunk_size == 10
        assert mock_adapter.run_checks.call_args.kwargs.get("chunk_size") == 10

        # 2. health with --chunk-size
        mock_adapter.run_checks.reset_mock()
        exit_code_health = main([
            "health",
            "--project", str(tmp_path),
            "--provider", "dbt",
            "--chunk-size", "25",
        ])
        assert exit_code_health == 0
        assert cfg.chunk_size == 25
        assert mock_adapter.run_checks.call_args.kwargs.get("chunk_size") == 25


def test_cli_docs_and_action_chunk_size_flag(tmp_path: Path):
    from unittest.mock import patch

    with patch("tff.core.docs.generate_docs_dashboard", return_value=Path("out.html")) as mock_docs:
        exit_code = main([
            "docs",
            "--project", str(tmp_path),
            "--provider", "dbt",
            "--chunk-size", "15",
        ])
        assert exit_code == 0
        assert mock_docs.call_args.kwargs.get("chunk_size") == 15

    with patch("tff.core.action.execute_action", return_value=0) as mock_action:
        exit_code = main([
            "action",
            "--project", str(tmp_path),
            "--provider", "dbt",
            "--chunk-size", "20",
        ])
        assert exit_code == 0
        args_passed = mock_action.call_args[0][0]
        assert args_passed.chunk_size == 20


@pytest.mark.parametrize("flag", ["-p", "--project"])
def test_cli_action_multi_project_flags(flag: str, tmp_path: Path) -> None:
    p1 = tmp_path / "p1"
    p2 = tmp_path / "p2"
    p1.mkdir()
    p2.mkdir()
    with patch("tff.core.action.execute_action", return_value=0) as mock_action:
        exit_code = main(["action", flag, str(p1), flag, str(p2)])
        assert exit_code == 0
        mock_action.assert_called_once()
        args = mock_action.call_args[0][0]
        assert args.projects == [p1.resolve(), p2.resolve()]
        assert args.project == p1.resolve()


@pytest.mark.parametrize("flag", ["-p", "--project"])
def test_cli_init_project_short_and_long_flags(
    flag: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = main(["init", flag, str(tmp_path)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Created fitness_functions.yaml" in captured.out
    assert (tmp_path / "fitness_functions.yaml").exists()


def test_cli_info_json_and_error_diagnostics(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from tff.core.exceptions import TffProviderError

    (tmp_path / "dbt_project.yml").touch()
    (tmp_path / "fitness_functions.yaml").write_text(
        "layers:\n  order: [staging, marts]\n", encoding="utf-8"
    )
    (tmp_path / "target").mkdir()
    manifest_data = {
        "metadata": {"adapter_type": "duckdb"},
        "nodes": {
            "model.pkg.stg_users": {
                "resource_type": "model",
                "name": "stg_users",
                "original_file_path": "models/stg_users.sql",
                "columns": {},
                "config": {"materialized": "table"},
                "depends_on": {"nodes": []},
            },
            "model.pkg.ephemeral_model": {
                "resource_type": "model",
                "name": "ephemeral_model",
                "original_file_path": "models/ephemeral_model.sql",
                "columns": {},
                "config": {"materialized": "ephemeral"},
                "depends_on": {"nodes": []},
            },
        },
        "sources": {
            "source.pkg.raw.users": {
                "resource_type": "source",
                "name": "users",
                "original_file_path": "models/sources.yml",
            }
        },
    }
    (tmp_path / "target" / "manifest.json").write_text(
        json.dumps(manifest_data), encoding="utf-8"
    )

    exit_code = main(["info", "-p", str(tmp_path), "--json"])
    assert exit_code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["provider"] == "dbt"
    assert payload["projects"] == [str(tmp_path.resolve())]
    assert payload["config_loaded"] is True
    assert payload["models_loaded"] == 1
    assert payload["external_sources"] == 1
    assert "dbt_project.yml" in payload["files"]
    assert "adapters" not in payload

    # Test --all-adapters in --json mode
    exit_code_all = main(["info", "-p", str(tmp_path), "--json", "--all-adapters"])
    assert exit_code_all == 0
    payload_all = json.loads(capsys.readouterr().out)
    assert "adapters" in payload_all
    assert payload_all["adapters"]["dbt"] == "core"
    assert payload_all["adapters"]["dataform"] == "core"

    # Missing manifest fallback in --json mode
    (tmp_path / "target" / "manifest.json").unlink()
    exit_code_no_manifest = main(["info", "-p", str(tmp_path), "--json"])
    assert exit_code_no_manifest == 0
    payload_no_manifest = json.loads(capsys.readouterr().out)
    assert payload_no_manifest["models_loaded"] == 0
    assert payload_no_manifest["external_sources"] == 0

    # Adapter error in non-json and json modes
    with patch(
        "tff.core.cli._get_adapter",
        side_effect=TffProviderError("Adapter failed", provider="dbt"),
    ):
        assert main(["info", "-p", str(tmp_path), "--provider", "dbt"]) == 1
        err_cap = capsys.readouterr()
        assert "Error loading adapter" in err_cap.out
        assert "FAIL Error: Adapter failed" in err_cap.err

        assert main(["info", "-p", str(tmp_path), "--provider", "dbt", "--json"]) == 1
        err_cap_json = capsys.readouterr()
        assert err_cap_json.out == ""
        assert "FAIL Error: Adapter failed" in err_cap_json.err

    # Detection failure in --json mode keeps stdout clean
    empty_dir = tmp_path / "empty_proj"
    empty_dir.mkdir()
    assert main(["info", "-p", str(empty_dir), "--json"]) == 1
    det_cap = capsys.readouterr()
    assert det_cap.out == ""
    assert "FAIL Error:" in det_cap.err


@pytest.mark.parametrize("cache_flag", ["--no-cache", "--clear-cache"])
def test_cli_docs_cache_flags(
    cache_flag: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch("tff.core.cli._detect_provider", return_value="dbt"),
        patch(
            "tff.core.docs.generate_docs_dashboard",
            return_value=tmp_path / "tff_report.html",
        ) as mock_docs,
    ):
        exit_code = main(["docs", "-p", str(tmp_path), cache_flag])
        assert exit_code == 0
        mock_docs.assert_called_once()
        captured = capsys.readouterr()
        if cache_flag == "--clear-cache":
            assert "Cleared" in captured.out


@pytest.mark.parametrize(
    "cli_module_name",
    ["tff.dbt.cli", "tff.dataform.cli", "tff.sqlmesh.cli"],
)
def test_deprecated_provider_cli_tff_error(
    tmp_path: Path, cli_module_name: str, capsys: pytest.CaptureFixture[str]
) -> None:
    import importlib
    from tff.core.exceptions import TffError

    cli_mod = importlib.import_module(cli_module_name)
    with (
        patch(f"{cli_module_name}.load_fitness_config"),
        patch(
            f"{cli_module_name}.run_all_checks",
            side_effect=TffError("Provider check failed", hint="Fix model SQL"),
        ),
    ):
        exit_code = cli_mod.main(["lint", "--project", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "FAIL Error: Provider check failed" in captured.err
        assert "● Hint: Fix model SQL" in captured.err


@pytest.mark.parametrize(
    ("query", "expected_match"),
    [
        ("analytics.orders", True),
        ("ANALYTICS.ORDERS", True),
        ("orders", True),
        ("orders.sql", True),
        ("unknown_model", False),
    ],
)
def test_find_model_by_name(query: str, expected_match: bool) -> None:
    from tff.core.cli import _find_model_by_name

    models = {
        "analytics.orders": _make_model(
            name="analytics.orders",
            path="models/analytics/orders.sql",
        )
    }
    match = _find_model_by_name(models, query)
    if expected_match:
        assert match is not None
        assert match.name == "analytics.orders"
    else:
        assert match is None


def test_render_complexity_inspection_smoke() -> None:
    from rich.console import Console
    from tff.core.cli import _render_complexity_inspection
    from tff.core.rules.sql_complexity import ComplexityInspection, DecisionPointDetail

    console = Console(record=True, width=100)
    inspection = ComplexityInspection(
        model_name="analytics.customers",
        path="models/analytics/customers.sql",
        dialect="duckdb",
        metrics={
            "decision_points": 20,
            "cte_count": 2,
            "join_count": 1,
            "line_count": 50,
            "nested_subquery_in_final_select": False,
        },
        thresholds={
            "decision_points": [15, 25],
            "cte_count": [8, 12],
            "join_count": [8, 12],
            "line_count": [250, 400],
        },
        decision_points=[
            DecisionPointDetail(
                kind="case",
                line=10,
                col=4,
                snippet="CASE WHEN status = 'a' THEN 1 END",
                cte_name="stg_users",
            )
        ],
        ctes=[],
        joins=[],
        nested_subquery=False,
        recommendations=["Model has 1 CASE/IF decision branch."],
    )

    _render_complexity_inspection(inspection, console=console)
    output = console.export_text()
    assert "Model Complexity Inspection: analytics.customers" in output
    assert "Decision Points" in output
    assert "stg_users" in output
    assert "Model has 1 CASE/IF decision branch." in output


def test_cli_explain_direct_sql_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sql_file = tmp_path / "test_model.sql"
    sql_file.write_text(
        "SELECT id, CASE WHEN a = 1 THEN 'yes' ELSE 'no' END FROM tbl WHERE x > 5 AND y < 10\n"
    )

    exit_code = main(["explain", "sqlcomplexity", str(sql_file)])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Model Complexity Inspection: test_model" in captured.out
    assert "Decision Points Breakdown" in captured.out

    # Test with --json
    exit_code_json = main(["explain", str(sql_file), "--json"])
    assert exit_code_json == 0
    captured_json = capsys.readouterr()
    payload = json.loads(captured_json.out)
    assert payload["model_name"] == "test_model"
    assert "decision_points" in payload
    assert len(payload["decision_points"]) >= 2


@pytest.mark.parametrize(
    "cli_args",
    [
        ["explain", "sqlcomplexity", "--model", "orders"],
        ["explain", "sqlcomplexity", "orders"],
        ["explain", "orders"],
        ["check", "explain", "sqlcomplexity", "for", "orders"],
        ["lint", "explain", "sqlcomplexity", "orders"],
    ],
)
def test_cli_explain_model_complexity_subcommand_variants(
    cli_args: list[str],
    capsys: pytest.CaptureFixture[str],
) -> None:
    model = _make_model(
        name="analytics.orders",
        path="models/analytics/orders.sql",
        dialect="duckdb",
        query="SELECT id, CASE WHEN status = 'shipped' THEN 1 ELSE 0 END AS is_shipped FROM raw.orders WHERE amount > 100",
    )

    mock_adapter = MagicMock()
    mock_adapter.load_models.return_value = {"analytics.orders": model}

    with (
        patch("tff.core.cli.detect_provider", return_value="sqlmesh"),
        patch("tff.core.cli.get_adapter", return_value=mock_adapter),
    ):
        exit_code = main(cli_args)
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Model Complexity Inspection: analytics.orders" in captured.out
        assert "Decision Points Breakdown" in captured.out


def test_cli_explain_model_complexity_json(capsys: pytest.CaptureFixture[str]) -> None:
    model = _make_model(
        name="analytics.orders",
        path="models/analytics/orders.sql",
        dialect="duckdb",
        query="SELECT id, CASE WHEN status = 'shipped' THEN 1 ELSE 0 END FROM raw.orders",
    )

    mock_adapter = MagicMock()
    mock_adapter.load_models.return_value = {"analytics.orders": model}

    with (
        patch("tff.core.cli.detect_provider", return_value="sqlmesh"),
        patch("tff.core.cli.get_adapter", return_value=mock_adapter),
    ):
        exit_code = main(["explain", "sqlcomplexity", "--model", "orders", "--json"])
        assert exit_code == 0
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["model_name"] == "analytics.orders"
        assert "metrics" in payload
        assert "decision_points" in payload


def test_cli_explain_model_not_found(capsys: pytest.CaptureFixture[str]) -> None:
    model = _make_model(name="analytics.orders")
    mock_adapter = MagicMock()
    mock_adapter.load_models.return_value = {"analytics.orders": model}

    with (
        patch("tff.core.cli.detect_provider", return_value="sqlmesh"),
        patch("tff.core.cli.get_adapter", return_value=mock_adapter),
    ):
        exit_code = main(["explain", "sqlcomplexity", "--model", "ordrs"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Model 'ordrs' not found in project." in captured.err
        assert "Did you mean 'orders'?" in captured.err or "Did you mean 'analytics.orders'?" in captured.err


def test_cli_explain_model_no_sql_content(capsys: pytest.CaptureFixture[str]) -> None:
    model = _make_model(name="analytics.orders", path="non_existent.sql", query=None)
    mock_adapter = MagicMock()
    mock_adapter.load_models.return_value = {"analytics.orders": model}

    with (
        patch("tff.core.cli.detect_provider", return_value="sqlmesh"),
        patch("tff.core.cli.get_adapter", return_value=mock_adapter),
    ):
        exit_code = main(["explain", "sqlcomplexity", "--model", "orders"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "No SQL content available for model 'analytics.orders'." in captured.err


def test_explain_single_check_sqlcomplexity_tip(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["explain", "sqlcomplexity"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "To inspect decision points in a specific model, run:" in captured.out
    assert "tff explain sqlcomplexity --model <model_name>" in captured.out


def test_find_model_by_name_edge_cases() -> None:
    from tff.core.cli import _find_model_by_name

    assert _find_model_by_name({}, "") is None
    assert _find_model_by_name({}, "orders") is None
    assert _find_model_by_name({"m": _make_model(name="m")}, "") is None

    # Mismatched key and name
    models = {"diff_key": _make_model(name="actual_model_name", path="models/m.sql")}
    assert _find_model_by_name(models, "actual_model_name") is not None

    # Normalized dbt model name
    models_dbt = {"model.pkg.users": _make_model(name="model.pkg.users", path="models/users.sql")}
    assert _find_model_by_name(models_dbt, "users") is not None


def test_render_complexity_inspection_branches(capsys: pytest.CaptureFixture[str]) -> None:
    from tff.core.cli import _render_complexity_inspection
    from tff.core.rules.sql_complexity import ComplexityInspection

    # Test with default console (console=None), val > fail, and no decision points
    inspection = ComplexityInspection(
        model_name="orders",
        path=None,
        dialect="duckdb",
        metrics={"decision_points": 30, "cte_count": 0, "join_count": 0, "line_count": 10},
        thresholds={"decision_points": [15, 25], "cte_count": [8, 12], "join_count": [8, 12], "line_count": [250, 400]},
        decision_points=[],
        ctes=[],
        joins=[],
        nested_subquery=False,
        recommendations=["Model has high decision points."],
    )
    _render_complexity_inspection(inspection)
    captured = capsys.readouterr()
    assert "Model Complexity Inspection: orders" in captured.out
    assert "No decision points found." in captured.out
    assert "FAIL" in captured.out


def test_render_complexity_inspection_unconfigured_metric_does_not_fail(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tff.core.cli import _render_complexity_inspection
    from tff.core.rules.sql_complexity import ComplexityInspection

    inspection = ComplexityInspection(
        model_name="unconfigured_model",
        path=None,
        dialect="duckdb",
        metrics={"decision_points": 8, "cte_count": 2, "join_count": 1, "line_count": 100},
        thresholds={"line_count": [250, 400]},
        decision_points=[],
        ctes=[],
        joins=[],
        nested_subquery=False,
        recommendations=["Model is within all maintainability thresholds."],
    )
    _render_complexity_inspection(inspection)
    captured = capsys.readouterr()
    assert "FAIL" not in captured.out
    assert "PASS" in captured.out
    assert "—" in captured.out


def test_handle_model_complexity_explain_adapter_error(capsys: pytest.CaptureFixture[str]) -> None:
    mock_adapter = MagicMock()
    mock_adapter.load_models.side_effect = RuntimeError("Adapter crash")

    with (
        patch("tff.core.cli.detect_provider", return_value="sqlmesh"),
        patch("tff.core.cli.get_adapter", return_value=mock_adapter),
    ):
        # Plain text
        exit_code = main(["explain", "sqlcomplexity", "--model", "orders"])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Failed to load project models: Adapter crash" in captured.err

        # JSON
        exit_code_json = main(["explain", "sqlcomplexity", "--model", "orders", "--json"])
        assert exit_code_json == 1
        captured_json = capsys.readouterr()
        assert "Failed to load project models: Adapter crash" in captured_json.out


def test_handle_model_complexity_explain_missing_model_and_sql_json(capsys: pytest.CaptureFixture[str]) -> None:
    # 1. Missing model with --json
    mock_adapter = MagicMock()
    mock_adapter.load_models.return_value = {"orders": _make_model(name="orders")}

    with (
        patch("tff.core.cli.detect_provider", return_value="sqlmesh"),
        patch("tff.core.cli.get_adapter", return_value=mock_adapter),
    ):
        exit_code = main(["explain", "sqlcomplexity", "--model", "missing_model", "--json"])
        assert exit_code == 1
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["error"] == "Model 'missing_model' not found."

    # 2. Model with no SQL with --json
    model_no_sql = _make_model(name="empty_orders", path="non_existent.sql", query=None)
    mock_adapter.load_models.return_value = {"empty_orders": model_no_sql}
    with (
        patch("tff.core.cli.detect_provider", return_value="sqlmesh"),
        patch("tff.core.cli.get_adapter", return_value=mock_adapter),
    ):
        exit_code = main(["explain", "sqlcomplexity", "--model", "empty_orders", "--json"])
        assert exit_code == 1
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert "No SQL content available" in payload["error"]


def test_handle_explain_multi_check_category_table(capsys: pytest.CaptureFixture[str]) -> None:
    # Multiple checks in metadata category
    exit_code = main(["explain", "metadata"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Rule / Check" in captured.out
    assert "no_missing_owner" in captured.out
    assert "sql_complexity" in captured.out


def test_find_model_by_name_dict_key_normalization() -> None:
    from tff.core.cli import _find_model_by_name

    model_obj = _make_model(name="custom_alias")
    # Dict key is qualified dbt name, normalize_model_name strips prefix
    models = {"model.analytics.stg_orders": model_obj}
    found = _find_model_by_name(models, "stg_orders")
    assert found is model_obj


def test_handle_model_complexity_explain_default_console(tmp_path: Path) -> None:
    from tff.core.cli import handle_model_complexity_explain

    sql_file = tmp_path / "model.sql"
    sql_file.write_text("SELECT 1 FROM tbl", encoding="utf-8")

    # Call without passing console argument (defaults to None, instantiating Console())
    exit_code = handle_model_complexity_explain(str(sql_file))
    assert exit_code == 0


@pytest.mark.parametrize(
    "provider,has_sqlmesh,sqlmesh_ver,expected_status",
    [
        ("dbt", False, "not installed", "dbt [dim](core)[/dim]"),
        ("dataform", False, "not installed", "dataform [dim](core)[/dim]"),
        ("sqlmesh", True, "0.236.0", "sqlmesh [dim](sqlmesh 0.236.0 enabled)[/dim]"),
        ("sqlmesh", True, "not installed", "sqlmesh [dim](sqlmesh extra enabled)[/dim]"),
        (
            "sqlmesh",
            False,
            "not installed",
            "sqlmesh [dim red](not enabled - install 'tff-core[sqlmesh]')[/dim red]",
        ),
        ("custom_engine", False, "not installed", "custom_engine [dim](plugin)[/dim]"),
    ],
)
def test_format_provider_status_display(
    provider: str,
    has_sqlmesh: bool,
    sqlmesh_ver: str,
    expected_status: str,
) -> None:
    from tff.core.cli import _format_provider_status_display

    with (
        patch("importlib.util.find_spec", return_value=MagicMock() if has_sqlmesh else None),
        patch("tff.core.cli._get_package_version", return_value=sqlmesh_ver),
    ):
        result = _format_provider_status_display(provider)
        assert result == expected_status


@pytest.mark.parametrize(
    "pkg_name,dist_name,version,expected",
    [
        ("tff-core", "tff-core", "1.2.3", "1.2.3"),
        ("tff-core", "tff_core", "1.2.3", "1.2.3"),
        ("missing_pkg", "other_pkg", "1.0.0", "not installed"),
    ],
)
def test_get_package_version_target_site_packages(
    pkg_name: str, dist_name: str, version: str, expected: str
) -> None:
    from tff.core.cli import _get_package_version

    mock_dist = MagicMock()
    mock_dist.metadata.get.return_value = dist_name
    mock_dist.version = version

    with patch("importlib.metadata.distributions", return_value=[mock_dist]):
        res = _get_package_version(pkg_name, target_site_packages=["/fake/site-packages"])
        assert res == expected


def test_get_package_version_fallback_and_error() -> None:
    from tff.core.cli import _get_package_version

    with patch("importlib.metadata.version", return_value="2.0.0"):
        assert _get_package_version("tff-core") == "2.0.0"

    with patch("importlib.metadata.version", side_effect=Exception("not found")):
        assert _get_package_version("unknown-pkg") == "not installed"
















