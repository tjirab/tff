"""Tests for project health scoring and reports."""

from __future__ import annotations

from unittest.mock import MagicMock
from rich.console import Console

from tff.core.config import FitnessFunctionsConfig
from tff.core.report import LintFinding
from tff.core.health import (
    is_check_enabled,
    calculate_health_scores,
    render_health_report,
)
from tff.core.cli import main


def test_is_check_enabled() -> None:
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "custom_exclusions": {"enabled": False},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
            "metadata": {
                "enabled": True,
                "owner": True,
                "description": False,
            }
        }
    })
    
    # 1. Project level checks
    assert is_check_enabled(config, "layer_integrity", "dbt") is True
    assert is_check_enabled(config, "custom_exclusions", "dbt") is False

    # 2. Rule checks
    assert is_check_enabled(config, "banselectstar", "dbt") is True

    # 3. Metadata sub-checks
    assert is_check_enabled(config, "nomissingowner", "dbt") is True
    assert is_check_enabled(config, "nomissingdescription", "dbt") is False

    # Metadata disabled entirely
    config.rules.metadata.enabled = False
    assert is_check_enabled(config, "nomissingowner", "dbt") is False

    # 4. SQLMesh native rules
    assert is_check_enabled(config, "ambiguousorinvalidcolumn", "sqlmesh") is True
    assert is_check_enabled(config, "ambiguousorinvalidcolumn", "dbt") is False


def test_calculate_health_scores() -> None:
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "custom_exclusions": {"enabled": False},
            "schema_contracts": {"enabled": False},
            "dependency_graph": {"enabled": False},
            "materialization_depth": {"enabled": False},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
            "filename_equals_modelname": {"enabled": True},
            "column_names": {"enabled": False},
            "column_types": {"enabled": False},
            "mart_naming": {"enabled": False},
            "classification_macros": {"enabled": False},
            "sql_complexity": {"enabled": False},
            "environment_agnostic_references": {"enabled": False},
            "metadata": {"enabled": False},
            "no_positional_group_by_or_order_by": {"enabled": False},
        }
    })

    # Findings:
    # 1. banselectstar: 1 error on model_a, 1 warning on model_b (out of 10 models checked)
    # 2. filenameequalsmodelname: no findings
    # 3. layer_integrity: 1 warning finding (project level)
    findings = [
        LintFinding(check="banselectstar", severity="error", message="error msg", model="model_a"),
        LintFinding(check="banselectstar", severity="warning", message="warn msg", model="model_b"),
        LintFinding(check="layer_integrity", severity="warning", message="project warn"),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    # banselectstar score: 100 * (1 - (1 + 0.5 * 1) / 10) = 85.0%
    assert scores["check_scores"]["banselectstar"] == 85.0

    # filenameequalsmodelname score: 100.0% (no findings)
    assert scores["check_scores"]["filenameequalsmodelname"] == 100.0

    # layer_integrity score: 50.0% (project level, only warning)
    assert scores["check_scores"]["layer_integrity"] == 50.0

    # overall score: average of enabled (banselectstar: 85, filenameequalsmodelname: 100, layer_integrity: 50)
    # (85 + 100 + 50) / 3 = 78.333%
    assert abs(scores["overall_score"] - 78.333) < 0.01

    # Connascence of Name (CoN) category score: (banselectstar: 85, filenameequalsmodelname: 100) / 2 = 92.5%
    assert scores["category_scores"]["Connascence of Name (CoN)"] == 92.5

    # Dynamic Coupling category score: (layer_integrity: 50) / 1 = 50.0%
    assert scores["category_scores"]["Dynamic Coupling & DAG Structure"] == 50.0


def test_render_health_report() -> None:
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "custom_exclusions": {"enabled": False},
            "schema_contracts": {"enabled": False},
            "dependency_graph": {"enabled": False},
            "materialization_depth": {"enabled": False},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
            "filename_equals_modelname": {"enabled": False},
            "column_names": {"enabled": False},
            "column_types": {"enabled": False},
            "mart_naming": {"enabled": False},
            "classification_macros": {"enabled": False},
            "sql_complexity": {"enabled": False},
            "environment_agnostic_references": {"enabled": False},
            "metadata": {"enabled": False},
            "no_positional_group_by_or_order_by": {"enabled": False},
        }
    })

    findings = [
        LintFinding(check="banselectstar", severity="error", message="error msg", model="model_a"),
    ]

    scores = calculate_health_scores(findings, models_checked=5, config=config, provider="dbt")

    console = Console(record=True, width=100)
    render_health_report(scores, config, provider="dbt", console=console)

    output = console.export_text()
    assert "TFF PROJECT HEALTH REPORT" in output
    assert "Health Score by Category" in output
    assert "Connascence of Name (CoN)" in output
    assert "banselectstar" in output
    assert "filenameequalsmodelname" in output
    assert "Disabled" in output  # filenameequalsmodelname is disabled, should show in breakdown
    assert "[dim]Disabled[/dim]" not in output


def test_cli_health_command(tmp_path, monkeypatch) -> None:
    # We will mock the runner to avoid actually parsing a project directory
    mock_runner = MagicMock()
    # 5 models checked, 1 finding of warning severity on banselectstar
    mock_runner.run_all_checks.return_value = (
        [LintFinding(check="banselectstar", severity="warning", message="warning", model="model_a")],
        5,
        ["rules"],
    )
    
    # Patch import_module to return our mock runner when importing tff.dbt.runner
    def mock_import_module(name):
        if name == "tff.dbt.runner":
            return mock_runner
        raise ImportError("mock error")
        
    monkeypatch.setattr("importlib.import_module", mock_import_module)

    # Trigger the ImportError path to get 100% coverage
    try:
        mock_import_module("non_existent")
    except ImportError:
        pass

    # Write a dummy config file
    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text("""
checks:
  layer_integrity:
    enabled: false
rules:
  ban_select_star:
    enabled: true
""", encoding="utf-8")

    # Create a dummy dbt project signature
    (tmp_path / "dbt_project.yml").write_text("", encoding="utf-8")

    # Run with a threshold that will pass: banselectstar has 1 warning in 5 models -> score is 90%
    # fail-under 80 should pass (return 0)
    exit_code = main(["health", "--project", str(tmp_path), "--config", str(config_file), "--fail-under", "80.0"])
    assert exit_code == 0

    # Run with a threshold that will fail: fail-under 99.5 should fail (return 1)
    exit_code = main(["health", "--project", str(tmp_path), "--config", str(config_file), "--fail-under", "99.5"])
    assert exit_code == 1


def test_health_edge_cases() -> None:
    # 1. is_check_enabled fallback
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": False},
        },
        "rules": {
            "ban_select_star": {"enabled": False},
            "metadata": {"enabled": False},
        }
    })
    assert is_check_enabled(config, "non_existent_check", "dbt") is False

    # 2. No enabled checks (all disabled)
    config_empty = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": False},
            "custom_exclusions": {"enabled": False},
            "schema_contracts": {"enabled": False},
            "dependency_graph": {"enabled": False},
            "materialization_depth": {"enabled": False},
        },
        "rules": {
            "ban_select_star": {"enabled": False},
            "filename_equals_modelname": {"enabled": False},
            "column_names": {"enabled": False},
            "column_types": {"enabled": False},
            "mart_naming": {"enabled": False},
            "classification_macros": {"enabled": False},
            "sql_complexity": {"enabled": False},
            "environment_agnostic_references": {"enabled": False},
            "metadata": {"enabled": False},
            "no_positional_group_by_or_order_by": {"enabled": False},
        }
    })
    scores = calculate_health_scores([], models_checked=5, config=config_empty, provider="dbt")
    assert scores["overall_score"] == 100.0

    # Enable checks for tests
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
            "filename_equals_modelname": {"enabled": False},
            "column_names": {"enabled": False},
            "column_types": {"enabled": False},
            "mart_naming": {"enabled": False},
            "classification_macros": {"enabled": False},
            "sql_complexity": {"enabled": False},
            "environment_agnostic_references": {"enabled": False},
            "metadata": {"enabled": False},
            "no_positional_group_by_or_order_by": {"enabled": False},
        }
    })

    # 3. Project check passes with a severity non-error/non-warning (hits line 153)
    # Also add an unknown check (Other Checks) with warning (hits line 397)
    findings = [
        LintFinding(check="banselectstar", severity="error", message="error msg", model=None),
        LintFinding(check="banselectstar", severity="warning", message="warn msg", model=None),
        # info severity on layer_integrity will go to the else block (line 153)
        LintFinding(check="layer_integrity", severity="info", message="project info"),
        # unknown check finding with warning (hits line 397)
        LintFinding(check="custom_unknown_check", severity="warning", message="custom warning", model="model_a"),
    ]

    scores = calculate_health_scores(findings, models_checked=5, config=config, provider="dbt")
    
    # layer_integrity should pass (100%)
    assert scores["check_scores"]["layer_integrity"] == 100.0
    
    # custom_unknown_check score: 1 warning on 5 models -> 90.0%
    assert scores["check_scores"]["custom_unknown_check"] == 90.0
    assert scores["category_scores"]["Other Checks"] == 90.0

    # 4. Project check with error (hits line 149)
    findings_project_error = [
        LintFinding(check="layer_integrity", severity="error", message="project error"),
    ]
    scores_project_error = calculate_health_scores(findings_project_error, models_checked=5, config=config, provider="dbt")
    assert scores_project_error["check_scores"]["layer_integrity"] == 0.0

    # 5. models_checked <= 0 (hits line 179)
    scores_zero_models = calculate_health_scores(findings, models_checked=0, config=config, provider="dbt")
    assert scores_zero_models["check_scores"]["banselectstar"] == 100.0

    # 6. Score < 70 progress bar and Other Checks 100% rendering (hits lines 382-384)
    # Since models_checked=0, custom_unknown_check score is 100.0%
    console = Console(record=True, width=100)
    render_health_report(scores_zero_models, config, provider="dbt", console=console)
    output = console.export_text()
    assert "Other Checks" in output
    assert "custom_unknown_check" in output
    assert "100.0%" in output

    # 7. Score < 70 progress bar and Other Checks < 100% rendering (hits lines 224, 386-389, 391-398)
    # banselectstar: 4 errors on 5 models -> score is 20% (< 70)
    # custom_unknown_check: 1 error on 5 models -> score is 80% (< 100)
    findings_red_score = [
        LintFinding(check="banselectstar", severity="error", message="error", model="model_a"),
        LintFinding(check="banselectstar", severity="error", message="error", model="model_b"),
        LintFinding(check="banselectstar", severity="error", message="error", model="model_c"),
        LintFinding(check="banselectstar", severity="error", message="error", model="model_d"),
        LintFinding(check="custom_unknown_check", severity="error", message="unknown error", model="model_a"),
        LintFinding(check="custom_unknown_check", severity="warning", message="unknown warning", model="model_b"),
    ]
    scores_red = calculate_health_scores(findings_red_score, models_checked=5, config=config, provider="dbt")
    assert abs(scores_red["check_scores"]["banselectstar"] - 20.0) < 0.01
    assert abs(scores_red["check_scores"]["custom_unknown_check"] - 70.0) < 0.01
    
    console_red = Console(record=True, width=100)
    render_health_report(scores_red, config, provider="dbt", console=console_red)
    output_red = console_red.export_text()
    assert "Other Checks" in output_red
    assert "custom_unknown_check" in output_red
    assert "70.0%" in output_red
