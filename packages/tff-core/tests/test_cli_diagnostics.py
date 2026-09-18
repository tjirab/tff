"""Tests for human-readable CLI error diagnostics and top-level exception boundary."""

from __future__ import annotations

import io
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

from rich.console import Console

from tff.core import render_cli_error
from tff.core.cli import _is_debug_requested, main
from tff.core.exceptions import (
    TffConfigError,
    TffError,
    TffManifestNotFoundError,
    TffModelError,
)


def test_render_cli_error_reexport():
    """render_cli_error should be exported from tff.core."""
    import tff.core

    assert hasattr(tff.core, "render_cli_error")
    assert tff.core.render_cli_error is render_cli_error


def test_render_cli_error_minimal():
    """Renders basic error without bullets or hint."""
    err = TffError("Something went wrong")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True, width=120)

    render_cli_error(err, console=console)
    output = buf.getvalue()

    assert "✖ Error: Something went wrong" in output
    assert "•" not in output
    assert "Hint:" not in output


def test_render_cli_error_default_console(capsys):
    """Renders to stderr by default if no console is provided."""
    err = TffError("Default console test")
    render_cli_error(err)

    captured = capsys.readouterr()
    assert "✖ Error: Default console test" in captured.err
    assert captured.out == ""


def test_render_cli_error_full_context():
    """Renders model, path, rule, provider, operation, custom details, and hint."""
    err = TffModelError(
        "Failed to resolve relation",
        hint="Define the relation in sources.yml or check spelling.",
        model_name="stg_orders",
        path=Path("models/staging/stg_orders.sql"),
        details={
            "rule": "ban_select_star",
            "provider": "dbt",
            "operation": "parse_ast",
            "custom_flag": "active",
            "none_value": None,
            "errno": 2,  # ignored
            "original_error": "Syntax error",  # ignored
            "expected_type": "file",  # ignored
        },
    )
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True, width=120)

    render_cli_error(err, console=console)
    output = buf.getvalue()

    assert "✖ Error: Failed to resolve relation" in output
    assert "• Model: stg_orders" in output
    assert "• Path: models/staging/stg_orders.sql" in output
    assert "• Rule: ban_select_star" in output
    assert "• Provider: dbt" in output
    assert "• Operation: parse_ast" in output
    assert "• Custom Flag: active" in output
    assert "Errno" not in output
    assert "Original Error" not in output
    assert "Expected Type" not in output
    assert "None Value" not in output
    assert "• Hint: Define the relation in sources.yml or check spelling." in output


def test_render_cli_error_rule_fallbacks():
    """Checks rule_name and check fallback keys in details."""
    err1 = TffError("Rule name test", details={"rule_name": "mart_naming"})
    buf1 = io.StringIO()
    console1 = Console(file=buf1, force_terminal=False, no_color=True)
    render_cli_error(err1, console=console1)
    assert "• Rule: mart_naming" in buf1.getvalue()

    err2 = TffError("Check test", details={"check": "layer_dependency"})
    buf2 = io.StringIO()
    console2 = Console(file=buf2, force_terminal=False, no_color=True)
    render_cli_error(err2, console=console2)
    assert "• Rule: layer_dependency" in buf2.getvalue()


def test_render_cli_error_escapes_markup():
    """Rich markup characters in message, paths, and hints should be escaped."""
    err = TffError(
        "Invalid tag [bold]found[/bold] in regex [a-z]+",
        hint="Do not use [brackets] without escaping.",
        details={"path": "path/[bracket_dir]/file.sql"},
    )
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True, width=120)

    render_cli_error(err, console=console)
    output = buf.getvalue()

    assert "[bold]found[/bold]" in output
    assert "[a-z]+" in output
    assert "[brackets]" in output
    assert "path/[bracket_dir]/file.sql" in output


def test_render_cli_error_standard_exception_and_empty():
    """Non-TffError exceptions and empty message fallback."""
    exc = ValueError("Plain value error")
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True)
    render_cli_error(exc, console=console)
    assert "✖ Error: Plain value error" in buf.getvalue()

    empty_exc = Exception("")
    buf_empty = io.StringIO()
    console_empty = Console(file=buf_empty, force_terminal=False, no_color=True)
    render_cli_error(empty_exc, console=console_empty)
    assert "✖ Error: An unknown error occurred." in buf_empty.getvalue()


def test_render_cli_error_non_dict_details():
    """Details that is not a dict should not raise."""
    err = TffError("Error message")
    err.details = "not a dict"  # type: ignore[assignment]
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True)
    render_cli_error(err, console=console)
    assert "✖ Error: Error message" in buf.getvalue()


def test_is_debug_requested_variants(monkeypatch):
    """_is_debug_requested handles --debug in argv, sys.argv, and TFF_DEBUG."""
    # 1. Neither
    monkeypatch.delenv("TFF_DEBUG", raising=False)
    assert not _is_debug_requested(["lint", "--project", "."])

    # 2. In explicit argv
    assert _is_debug_requested(["lint", "--debug"])

    # 3. Via TFF_DEBUG env var
    monkeypatch.setenv("TFF_DEBUG", "1")
    assert _is_debug_requested(["lint"])

    # 4. Via sys.argv fallback when argv is None
    monkeypatch.delenv("TFF_DEBUG", raising=False)
    monkeypatch.setattr(sys, "argv", ["tff", "check", "--debug"])
    assert _is_debug_requested(None)

    monkeypatch.setattr(sys, "argv", ["tff", "check"])
    assert not _is_debug_requested(None)


def test_main_handles_tff_error(capsys):
    """TffError is rendered via render_cli_error to stderr, exiting with code 1."""
    err = TffConfigError(
        "fitness_functions.yaml parse error",
        hint="Check YAML syntax on line 12.",
        path=Path("fitness_functions.yaml"),
    )

    with patch("tff.core.cli._main_impl", side_effect=err):
        exit_code = main(["lint"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "✖ Error: fitness_functions.yaml parse error" in captured.err
    assert "• Path: fitness_functions.yaml" in captured.err
    assert "• Hint: Check YAML syntax on line 12." in captured.err
    assert "Traceback" not in captured.err


def test_main_handles_keyboard_interrupt(capsys):
    """KeyboardInterrupt prints 'Aborted by user.' to stderr and exits with 130."""
    with patch("tff.core.cli._main_impl", side_effect=KeyboardInterrupt()):
        exit_code = main(["lint"])
        assert exit_code == 130

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Aborted by user." in captured.err


def test_main_handles_unexpected_exception_no_debug(capsys, monkeypatch):
    """Unexpected exception without debug prints polite crash summary with issue tracker link."""
    monkeypatch.delenv("TFF_DEBUG", raising=False)

    with patch("tff.core.cli._main_impl", side_effect=RuntimeError("Null pointer in AST parser")):
        exit_code = main(["lint"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "✖ Unexpected Error: Null pointer in AST parser" in captured.err
    assert "https://github.com/tjirab/tff/issues" in captured.err
    assert "Re-run with --debug or set TFF_DEBUG=1" in captured.err
    assert "Traceback" not in captured.err


def test_main_handles_unexpected_exception_with_debug_flag(capsys, monkeypatch):
    """Unexpected exception with --debug flag prints full Rich traceback."""
    monkeypatch.delenv("TFF_DEBUG", raising=False)

    with patch("tff.core.cli._main_impl", side_effect=RuntimeError("Null pointer in AST parser")):
        exit_code = main(["lint", "--debug"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback (most recent call last)" in captured.err
    assert "Null pointer in AST parser" in captured.err


def test_main_handles_unexpected_exception_with_tff_debug_env(capsys, monkeypatch):
    """Unexpected exception with TFF_DEBUG=1 env var prints full Rich traceback."""
    monkeypatch.setenv("TFF_DEBUG", "1")

    with patch("tff.core.cli._main_impl", side_effect=RuntimeError("Null pointer in AST parser")):
        exit_code = main(["lint"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Traceback (most recent call last)" in captured.err
    assert "Null pointer in AST parser" in captured.err


def test_stream_discipline_with_json_and_tff_error(capsys):
    """When --json is passed, error messages strictly go to stderr, keeping stdout clean."""
    err = TffManifestNotFoundError("manifest.json not found", provider="dbt")

    with patch("tff.core.cli._main_impl", side_effect=err):
        exit_code = main(["lint", "--json"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "✖ Error: manifest.json not found" in captured.err
    assert "• Provider: dbt" in captured.err


def test_main_propagates_tff_error_from_load_config(tmp_path: Path, capsys):
    """TffConfigError in load_fitness_config bubbles up to main exception boundary."""
    (tmp_path / "dbt_project.yml").touch()
    err = TffConfigError("Invalid YAML format in config", hint="Fix indentation.", path=tmp_path / "fitness_functions.yaml")

    with patch("tff.core.cli._get_adapter"), \
         patch("tff.core.cli.load_fitness_config", side_effect=err):
        exit_code = main(["lint", "--project", str(tmp_path), "--provider", "dbt"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert "✖ Error: Invalid YAML format in config" in captured.err
    assert "• Hint: Fix indentation." in captured.err


def test_main_propagates_tff_error_from_run_checks(tmp_path: Path, capsys):
    """TffError in adapter.run_checks bubbles up to main exception boundary."""
    (tmp_path / "dbt_project.yml").touch()
    mock_adapter = MagicMock()
    mock_adapter.provider_name = "dbt"
    err = TffModelError("Syntax error parsing model SQL", model_name="orders", hint="Verify syntax in orders.sql")
    mock_adapter.run_checks.side_effect = err

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.load_fitness_config", return_value=MagicMock(_config_file_found=True)):
        exit_code = main(["lint", "--project", str(tmp_path), "--provider", "dbt"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert "✖ Error: Syntax error parsing model SQL" in captured.err
    assert "• Model: orders" in captured.err
    assert "• Hint: Verify syntax in orders.sql" in captured.err


def test_main_propagates_tff_error_from_autofix_rerun(tmp_path: Path, capsys):
    """TffError in rerun checks after autofix bubbles up to main exception boundary."""
    from tff.core.report import LintFinding
    from tff.core.model import ModelRepresentation

    (tmp_path / "dbt_project.yml").touch()
    mock_adapter = MagicMock()
    mock_adapter.provider_name = "dbt"
    mock_adapter.load_models.return_value = {
        "orders": ModelRepresentation(name="orders", path=str(tmp_path / "orders.sql"), dialect="ansi")
    }
    initial_finding = LintFinding(
        check="nopositionalgroupbyororderby",
        severity="error",
        model="orders",
        path="orders.sql",
        message="Positional group by used",
    )
    rerun_err = TffModelError("Failed to parse orders after autofix", model_name="orders")
    mock_adapter.run_checks.side_effect = [
        ([initial_finding], 1, ["rules"]),
        rerun_err,
    ]

    with patch("tff.core.cli._get_adapter", return_value=mock_adapter), \
         patch("tff.core.cli.load_fitness_config", return_value=MagicMock(_config_file_found=True)), \
         patch("tff.core.autofix.apply_autofixes", return_value=["Fixed orders"]):
        exit_code = main(["lint", "--project", str(tmp_path), "--provider", "dbt", "--fix"])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert "✖ Error: Failed to parse orders after autofix" in captured.err


def test_main_propagates_tff_error_from_docs(tmp_path: Path, capsys):
    """TffError in generate_docs_dashboard bubbles up to main exception boundary."""
    (tmp_path / "dbt_project.yml").touch()
    err = TffError("Failed to compile docs template", hint="Check template files.")

    with patch("tff.core.cli._detect_provider", return_value="dbt"), \
         patch("tff.core.docs.generate_docs_dashboard", side_effect=err):
        exit_code = main(["docs", "--project", str(tmp_path)])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert "✖ Error: Failed to compile docs template" in captured.err
    assert "• Hint: Check template files." in captured.err


def test_main_propagates_tff_error_from_init(tmp_path: Path, capsys):
    """TffError in init_fitness_config bubbles up to main exception boundary."""
    err = TffError("Permission denied initializing config", hint="Check write permissions.")

    with patch("tff.core.cli.init_fitness_config", side_effect=err):
        exit_code = main(["init", "--project", str(tmp_path)])
        assert exit_code == 1

    captured = capsys.readouterr()
    assert "✖ Error: Permission denied initializing config" in captured.err
    assert "• Hint: Check write permissions." in captured.err

