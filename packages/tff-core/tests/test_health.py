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
            "duplicate_ctes": {"enabled": False},
            "connascence_of_value": {"enabled": False},
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
  duplicate_ctes:
    enabled: false
  connascence_of_value:
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


# ---------------------------------------------------------------------------
# Scope filtering
# ---------------------------------------------------------------------------

def test_calculate_health_scores_with_scope() -> None:
    """Findings outside the scope are excluded; models_checked is re-derived."""
    config = FitnessFunctionsConfig.model_validate({
        "rules": {
            "ban_select_star": {"enabled": True},
        }
    })

    findings = [
        # In scope
        LintFinding(
            check="banselectstar", severity="error", message="err",
            model="model_a", path="models/marts/marketing/model_a.sql",
        ),
        LintFinding(
            check="banselectstar", severity="warning", message="warn",
            model="model_b", path="models/marts/marketing/model_b.sql",
        ),
        # Out of scope
        LintFinding(
            check="banselectstar", severity="error", message="err",
            model="model_c", path="models/sources/model_c.sql",
        ),
    ]

    scores = calculate_health_scores(
        findings, models_checked=10, config=config, provider="dbt",
        scope=["models/marts/marketing"],
    )

    # Only the 2 in-scope findings remain; models_checked becomes 2 (unique paths)
    # E=1, W=1 (warning_models = {model_b} - {model_a} = {model_b}), M=2
    # score = 100 * (1 - (1 + 0.5*1) / 2) = 100 * (1 - 0.75) = 25.0
    assert abs(scores["check_scores"]["banselectstar"] - 25.0) < 0.01


def test_calculate_health_scores_with_scoped_models_count() -> None:
    """When scoped_models_count is explicitly passed, it is used as denominator."""
    config = FitnessFunctionsConfig.model_validate({
        "rules": {
            "ban_select_star": {"enabled": True},
        }
    })

    findings = [
        LintFinding(
            check="banselectstar", severity="error", message="err",
            model="model_a", path="models/marts/marketing/model_a.sql",
        ),
    ]

    scores = calculate_health_scores(
        findings,
        models_checked=50,
        config=config,
        provider="dbt",
        scope=["models/marts/marketing"],
        scoped_models_count=10,
    )

    # 1 error among 10 models in scope: score = 100 * (1 - 1/10) = 90.0
    assert abs(scores["check_scores"]["banselectstar"] - 90.0) < 0.01
    expected_overall = sum(scores["check_scores"].values()) / len(scores["enabled_checks"])
    assert abs(scores["overall_score"] - expected_overall) < 0.01


def test_calculate_health_scores_scope_excludes_all() -> None:
    """When scope matches nothing, scores default to 100 (no models, no findings)."""
    config = FitnessFunctionsConfig.model_validate({
        "rules": {"ban_select_star": {"enabled": True}},
    })
    findings = [
        LintFinding(
            check="banselectstar", severity="error", message="err",
            model="model_a", path="models/sources/model_a.sql",
        ),
    ]
    scores = calculate_health_scores(
        findings, models_checked=5, config=config, provider="dbt",
        scope=["models/marts"],
    )
    # No findings survive the filter → 100%
    assert scores["check_scores"]["banselectstar"] == 100.0


def test_matches_scope_helper() -> None:
    from tff.core.health import _matches_scope

    assert _matches_scope("models/marts/marketing/foo.sql", ["models/marts/marketing"]) is True
    assert _matches_scope("models/marts/finance/foo.sql", ["models/marts/marketing"]) is False
    # Exact prefix match (no trailing slash)
    assert _matches_scope("models/marts", ["models/marts"]) is True
    # None path → False
    assert _matches_scope(None, ["models/marts"]) is False
    # Multiple prefixes
    assert _matches_scope("models/sources/foo.sql", ["models/marts", "models/sources"]) is True


def test_domain_key_helper() -> None:
    from tff.core.health import _domain_key

    assert _domain_key("models/marts/marketing/model.sql") == "models/marts/marketing"
    assert _domain_key("models/sources/model.sql") == "models/sources"
    assert _domain_key(None) == "Project-level"
    # Path with no 'models' dir → returned as-is (hits the ValueError branch)
    assert _domain_key("some/other/path/model.sql") == "some/other/path/model.sql"
    # Path that is exactly 'models' with nothing after (hits the len guard)
    assert _domain_key("models") == "models"


# ---------------------------------------------------------------------------
# Domain-grouped health report rendering
# ---------------------------------------------------------------------------

def test_render_health_report_group_by_domain() -> None:
    config = FitnessFunctionsConfig.model_validate({
        "rules": {
            "ban_select_star": {"enabled": True},
            "filename_equals_modelname": {"enabled": True},
        }
    })

    findings = [
        LintFinding(
            check="banselectstar", severity="error", message="err A",
            model="model_a", path="models/sources/model_a.sql",
        ),
        LintFinding(
            check="banselectstar", severity="warning", message="warn B",
            model="model_b", path="models/marts/marketing/model_b.sql",
        ),
        LintFinding(
            check="filenameequalsmodelname", severity="error", message="err C",
            model="model_c", path="models/marts/marketing/model_c.sql",
        ),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    console = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console, group_by="domain")
    output = console.export_text()

    assert "Detailed Breakdown by Domain" in output
    # Both domain labels should appear
    assert "models/sources" in output
    assert "models/marts/marketing" in output
    # Check names appear inside the domain sections
    assert "banselectstar" in output
    assert "filenameequalsmodelname" in output


def test_render_health_report_group_by_domain_no_findings() -> None:
    """With no findings, domain breakdown shows 'No findings' message."""
    config = FitnessFunctionsConfig.model_validate({
        "rules": {"ban_select_star": {"enabled": True}},
    })

    scores = calculate_health_scores([], models_checked=5, config=config, provider="dbt")

    console = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console, group_by="domain")
    output = console.export_text()

    assert "Detailed Breakdown by Domain" in output
    assert "No findings" in output


def test_render_health_report_group_by_domain_project_level_findings() -> None:
    """Project-level findings (path=None) fall into a 'Project-level' section
    and exercise the domain_models_checked==0 branch (line 574)."""
    config = FitnessFunctionsConfig.model_validate({
        "checks": {"layer_integrity": {"enabled": True}},
    })

    findings = [
        # No path → project-level; domain_models_checked will be 0
        LintFinding(
            check="layer_integrity", severity="warning", message="proj warning",
            model=None, path=None,
        ),
    ]

    scores = calculate_health_scores(findings, models_checked=5, config=config, provider="dbt")

    console = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console, group_by="domain")
    output = console.export_text()

    assert "Detailed Breakdown by Domain" in output
    assert "Project-level" in output
    assert "layer_integrity" in output


def test_render_health_report_group_by_domain_perfect_domain() -> None:
    """A project-level finding with 'info' severity keeps check_score at 100%,
    which exercises the local_score==100.0 green-check branch (lines 577-579)
    via the domain_models_checked==0 path (line 574).
    """
    config = FitnessFunctionsConfig.model_validate({
        "checks": {"layer_integrity": {"enabled": True}},
    })

    # 'info' severity is neither 'error' nor 'warning' → score stays at 100.0
    findings = [
        LintFinding(
            check="layer_integrity", severity="info", message="informational",
            model=None, path=None,
        ),
    ]

    scores = calculate_health_scores(findings, models_checked=5, config=config, provider="dbt")
    # Confirm the check score is 100 (info severity doesn't penalise)
    assert scores["check_scores"]["layer_integrity"] == 100.0

    console = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console, group_by="domain")
    output = console.export_text()

    assert "Detailed Breakdown by Domain" in output
    assert "Project-level" in output
    assert "layer_integrity" in output
    assert "100.0%" in output


# ---------------------------------------------------------------------------
# CLI integration: --scope and --group-by domain
# ---------------------------------------------------------------------------

def test_cli_health_scope(tmp_path, monkeypatch) -> None:
    """--scope filters findings to in-scope models only."""
    from unittest.mock import MagicMock

    mock_runner = MagicMock()
    # Runner returns findings from two domains; --scope should restrict to sources
    mock_runner.run_all_checks.return_value = (
        [
            LintFinding(
                check="banselectstar", severity="error", message="err",
                model="model_a", path="models/sources/model_a.sql",
            ),
            LintFinding(
                check="banselectstar", severity="error", message="err",
                model="model_b", path="models/marts/marketing/model_b.sql",
            ),
        ],
        10,
        ["rules"],
    )

    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: mock_runner if name == "tff.dbt.runner" else (_ for _ in ()).throw(ImportError()),
    )

    # Only enable ban_select_star so it dominates the overall score
    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text(
        "checks:\n"
        "  layer_integrity:\n    enabled: false\n"
        "  custom_exclusions:\n    enabled: false\n"
        "  schema_contracts:\n    enabled: false\n"
        "  dependency_graph:\n    enabled: false\n"
        "  materialization_depth:\n    enabled: false\n"
        "  duplicate_ctes:\n    enabled: false\n"
        "  connascence_of_value:\n    enabled: false\n"
        "rules:\n"
        "  ban_select_star:\n    enabled: true\n"
        "  filename_equals_modelname:\n    enabled: false\n"
        "  column_names:\n    enabled: false\n"
        "  column_types:\n    enabled: false\n"
        "  mart_naming:\n    enabled: false\n"
        "  classification_macros:\n    enabled: false\n"
        "  sql_complexity:\n    enabled: false\n"
        "  environment_agnostic_references:\n    enabled: false\n"
        "  metadata:\n    enabled: false\n"
        "  no_positional_group_by_or_order_by:\n    enabled: false\n",
        encoding="utf-8",
    )
    (tmp_path / "dbt_project.yml").write_text("", encoding="utf-8")

    # With scope=models/sources only 1 model (model_a) is in scope → score = 0%
    # (1 error, 1 model → 100*(1-1/1) = 0%), fail-under 50 should fail
    exit_code = main([
        "health",
        "--project", str(tmp_path),
        "--config", str(config_file),
        "--scope", "models/sources",
        "--fail-under", "50.0",
    ])
    assert exit_code == 1


def test_cli_health_group_by_domain(tmp_path, monkeypatch) -> None:
    """--group-by domain reaches the domain rendering path without error."""
    from unittest.mock import MagicMock

    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = (
        [
            LintFinding(
                check="banselectstar", severity="warning", message="warn",
                model="model_a", path="models/sources/model_a.sql",
            ),
        ],
        5,
        ["rules"],
    )

    monkeypatch.setattr(
        "importlib.import_module",
        lambda name: mock_runner if name == "tff.dbt.runner" else (_ for _ in ()).throw(ImportError()),
    )

    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text(
        "rules:\n  ban_select_star:\n    enabled: true\n", encoding="utf-8"
    )
    (tmp_path / "dbt_project.yml").write_text("", encoding="utf-8")

    exit_code = main([
        "health",
        "--project", str(tmp_path),
        "--config", str(config_file),
        "--group-by", "domain",
    ])
    assert exit_code == 0


def test_configurable_weights_scoring() -> None:
    """Validate weighted category and overall health scores."""
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "schema_contracts": {"enabled": True},
            "custom_exclusions": {"enabled": False},
            "dependency_graph": {"enabled": False},
            "materialization_depth": {"enabled": False},
            "duplicate_ctes": {"enabled": False},
            "connascence_of_value": {"enabled": False},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
            "column_names": {"enabled": True},
            "filename_equals_modelname": {"enabled": False},
            "column_types": {"enabled": False},
            "mart_naming": {"enabled": False},
            "classification_macros": {"enabled": False},
            "sql_complexity": {"enabled": False},
            "environment_agnostic_references": {"enabled": False},
            "metadata": {"enabled": False},
            "no_positional_group_by_or_order_by": {"enabled": False},
        },
        "health": {
            "weights": {
                "layer_integrity": 3.0,
                "schema_contracts": 2.0,
                "column_names": 0.5,
            }
        }
    })

    findings = [
        LintFinding(check="layer_integrity", severity="warning", message="warn"),
        LintFinding(check="columnnames", severity="error", message="col error", model="model_a"),
        LintFinding(check="banselectstar", severity="error", message="star error 1", model="model_b"),
        LintFinding(check="banselectstar", severity="error", message="star error 2", model="model_c"),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    # Verify check weights resolved correctly
    assert scores["check_weights"]["layer_integrity"] == 3.0
    assert scores["check_weights"]["schema_contracts"] == 2.0
    assert scores["check_weights"]["columnnames"] == 0.5
    assert scores["check_weights"]["banselectstar"] == 1.0  # default

    # Verify individual check scores
    assert scores["check_scores"]["layer_integrity"] == 50.0
    assert scores["check_scores"]["schema_contracts"] == 100.0
    assert scores["check_scores"]["columnnames"] == 90.0
    assert scores["check_scores"]["banselectstar"] == 80.0

    # Overall score: (3.0*50 + 2.0*100 + 0.5*90 + 1.0*80) / (3.0 + 2.0 + 0.5 + 1.0)
    # = (150 + 200 + 45 + 80) / 6.5 = 475.0 / 6.5 = 73.0769%
    assert abs(scores["overall_score"] - (475.0 / 6.5)) < 0.001

    # Connascence of Name category score:
    # checks: columnnames (w=0.5, score=90.0), banselectstar (w=1.0, score=80.0)
    # = (0.5*90 + 1.0*80) / (0.5 + 1.0) = 125.0 / 1.5 = 83.333%
    assert abs(scores["category_scores"]["Connascence of Name (CoN)"] - (125.0 / 1.5)) < 0.001

    # Single check categories
    assert scores["category_scores"]["Dynamic Coupling & DAG Structure"] == 50.0
    assert scores["category_scores"]["Connascence of Type (CoT)"] == 100.0


def test_category_weights_and_overrides() -> None:
    """Validate category-level weights and individual check overrides."""
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "dependency_graph": {"enabled": True},
            "custom_exclusions": {"enabled": False},
            "schema_contracts": {"enabled": False},
            "materialization_depth": {"enabled": False},
            "duplicate_ctes": {"enabled": False},
            "connascence_of_value": {"enabled": False},
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
        },
        "health": {
            "weights": {
                # Category weight via exact name
                "Dynamic Coupling & DAG Structure": 2.0,
                # Check override inside the same category
                "layer_integrity": 4.0,
            }
        }
    })

    scores = calculate_health_scores([], models_checked=5, config=config, provider="dbt")
    # layer_integrity gets check override: 4.0
    assert scores["check_weights"]["layer_integrity"] == 4.0
    # dependency_graph gets category weight: 2.0
    assert scores["check_weights"]["dependency_graph"] == 2.0
    # banselectstar gets default: 1.0
    assert scores["check_weights"]["banselectstar"] == 1.0


def test_category_weight_aliases_and_category_weights_field() -> None:
    """Validate category aliases (e.g. dynamic_coupling, con) and category_weights field."""
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "dependency_graph": {"enabled": True},
            "layer_integrity": {"enabled": False},
            "custom_exclusions": {"enabled": False},
            "schema_contracts": {"enabled": False},
            "materialization_depth": {"enabled": False},
            "duplicate_ctes": {"enabled": False},
            "connascence_of_value": {"enabled": False},
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
        },
        "health": {
            "category_weights": {
                "dynamic_coupling": 2.5,
                "con": 1.5,
            }
        }
    })

    scores = calculate_health_scores([], models_checked=5, config=config, provider="dbt")
    assert scores["check_weights"]["dependency_graph"] == 2.5
    assert scores["check_weights"]["banselectstar"] == 1.5


def test_weights_edge_cases() -> None:
    """Validate edge cases such as all weights zero, custom unknown checks, and fallback."""
    config_zero = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "custom_exclusions": {"enabled": False},
            "schema_contracts": {"enabled": False},
            "dependency_graph": {"enabled": False},
            "materialization_depth": {"enabled": False},
            "duplicate_ctes": {"enabled": False},
            "connascence_of_value": {"enabled": False},
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
        },
        "health": {
            "weights": {
                "layer_integrity": 0.0,
                "ban_select_star": 0.0,
            }
        }
    })
    findings = [
        LintFinding(check="layer_integrity", severity="warning", message="w"),
        LintFinding(check="banselectstar", severity="error", message="e", model="m1"),
    ]
    scores_zero = calculate_health_scores(findings, models_checked=10, config=config_zero, provider="dbt")
    assert scores_zero["check_scores"]["layer_integrity"] == 50.0
    assert scores_zero["check_scores"]["banselectstar"] == 90.0
    # Fallback to unweighted category and overall average
    assert scores_zero["category_scores"]["Connascence of Name (CoN)"] == 90.0
    assert scores_zero["overall_score"] == 70.0

    # 2. Unknown check with custom weight
    config_unknown = FitnessFunctionsConfig.model_validate({
        "health": {
            "weights": {
                "custom_unknown_check": 3.0,
            }
        }
    })
    findings_unknown = [
        LintFinding(check="custom_unknown_check", severity="warning", message="w", model="m1"),
    ]
    scores_unknown = calculate_health_scores(findings_unknown, models_checked=10, config=config_unknown, provider="dbt")
    assert scores_unknown["check_weights"]["custom_unknown_check"] == 3.0
    assert scores_unknown["category_scores"]["Other Checks"] == 95.0

    # 3. Unknown check with weight 0.0 (tests unweighted fallback in Other Checks)
    config_unknown_zero = FitnessFunctionsConfig.model_validate({
        "health": {
            "weights": {
                "custom_unknown_check": 0.0,
            }
        }
    })
    scores_unknown_zero = calculate_health_scores(findings_unknown, models_checked=10, config=config_unknown_zero, provider="dbt")
    assert scores_unknown_zero["category_scores"]["Other Checks"] == 95.0

    # 4. Config without health attribute (tests fallback)
    from tff.core.health import get_check_weight
    assert get_check_weight("banselectstar", object()) == 1.0  # type: ignore[arg-type]


def test_configurable_penalties_project_level() -> None:
    """Validate configurable severity penalties for project-level checks."""
    # Custom percentage penalties
    config_pct = FitnessFunctionsConfig.model_validate({
        "checks": {"layer_integrity": {"enabled": True}},
        "health": {
            "penalties": {
                "project_error": 25.0,
                "project_warning": 10.0,
            }
        }
    })

    findings_err = [LintFinding(check="layer_integrity", severity="error", message="err")]
    scores_err = calculate_health_scores(findings_err, models_checked=5, config=config_pct, provider="dbt")
    # Score is 100 - 25 = 75%
    assert scores_err["check_scores"]["layer_integrity"] == 75.0

    findings_warn = [LintFinding(check="layer_integrity", severity="warning", message="warn")]
    scores_warn = calculate_health_scores(findings_warn, models_checked=5, config=config_pct, provider="dbt")
    # Score is 100 - 10 = 90%
    assert scores_warn["check_scores"]["layer_integrity"] == 90.0

    # Custom ratio penalties (0.30 -> 30%, 0.15 -> 15%)
    config_ratio = FitnessFunctionsConfig.model_validate({
        "checks": {"layer_integrity": {"enabled": True}},
        "health": {
            "penalties": {
                "project_error": 0.30,
                "project_warning": 0.15,
            }
        }
    })
    scores_ratio_err = calculate_health_scores(findings_err, models_checked=5, config=config_ratio, provider="dbt")
    assert scores_ratio_err["check_scores"]["layer_integrity"] == 70.0
    scores_ratio_warn = calculate_health_scores(findings_warn, models_checked=5, config=config_ratio, provider="dbt")
    assert scores_ratio_warn["check_scores"]["layer_integrity"] == 85.0


def test_configurable_penalties_model_level() -> None:
    """Validate configurable error and warning multipliers for model-level checks."""
    config = FitnessFunctionsConfig.model_validate({
        "rules": {"ban_select_star": {"enabled": True}},
        "health": {
            "penalties": {
                "error": 2.0,
                "warning": 0.1,
            }
        }
    })

    # 10 models checked:
    # 1 error -> 100 * (1 - 2.0 * 1 / 10) = 80%
    findings_err = [LintFinding(check="banselectstar", severity="error", message="err", model="m1")]
    scores_err = calculate_health_scores(findings_err, models_checked=10, config=config, provider="dbt")
    assert scores_err["check_scores"]["banselectstar"] == 80.0

    # 1 warning -> 100 * (1 - 0.1 * 1 / 10) = 99%
    findings_warn = [LintFinding(check="banselectstar", severity="warning", message="warn", model="m1")]
    scores_warn = calculate_health_scores(findings_warn, models_checked=10, config=config, provider="dbt")
    assert scores_warn["check_scores"]["banselectstar"] == 99.0


def test_nested_penalties_and_check_specific_overrides() -> None:
    """Validate nested model/project syntax and check-specific penalty overrides."""
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "dependency_graph": {"enabled": True},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
            "column_names": {"enabled": True},
        },
        "health": {
            "penalties": {
                "model": {"error": 1.0, "warning": 0.5},
                "project": {"error": 40.0, "warning": 20.0},
                "checks": {
                    "layer_integrity": {"error": 15.0, "warning": 5.0},
                    "ban_select_star": {"error": 0.5, "warning": 0.1},
                }
            }
        }
    })

    findings = [
        LintFinding(check="layer_integrity", severity="error", message="err"),
        LintFinding(check="dependency_graph", severity="error", message="err"),
        LintFinding(check="banselectstar", severity="error", message="err", model="m1"),
        LintFinding(check="columnnames", severity="error", message="err", model="m1"),
    ]
    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    # layer_integrity gets check override: 100 - 15 = 85%
    assert scores["check_scores"]["layer_integrity"] == 85.0
    # dependency_graph gets default project error: 100 - 40 = 60%
    assert scores["check_scores"]["dependency_graph"] == 60.0
    # banselectstar gets check override: 100 * (1 - 0.5 * 1 / 10) = 95%
    assert scores["check_scores"]["banselectstar"] == 95.0
    # columnnames gets default model error: 100 * (1 - 1.0 * 1 / 10) = 90%
    assert scores["check_scores"]["columnnames"] == 90.0


def test_render_health_report_custom_weights() -> None:
    """Validate that render_health_report prints custom weights when configured."""
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
        },
        "health": {
            "weights": {
                "layer_integrity": 3.0,
                # ban_select_star left at default 1.0
            }
        }
    })

    findings = [
        LintFinding(check="layer_integrity", severity="warning", message="w"),
        LintFinding(check="banselectstar", severity="warning", message="w", model="m1"),
    ]
    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    console = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console)
    output = console.export_text()

    # layer_integrity has weight 3.0 -> should display weight
    assert "layer_integrity · weight: 3" in output
    # banselectstar has weight 1.0 -> should display without weight string
    assert "banselectstar" in output
    assert "banselectstar · weight" not in output


def test_render_health_report_domain_custom_penalties() -> None:
    """Validate that domain breakdown rendering respects custom penalties."""
    config = FitnessFunctionsConfig.model_validate({
        "rules": {"ban_select_star": {"enabled": True}},
        "health": {
            "penalties": {
                "warning": 0.1,
            }
        }
    })
    findings = [
        LintFinding(
            check="banselectstar", severity="warning", message="warn",
            model="model_a", path="models/sources/model_a.sql",
        ),
    ]
    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    console = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console, group_by="domain")
    output = console.export_text()

    assert "Detailed Breakdown by Domain" in output
    assert "models/sources" in output
    # With 1 warning and penalty 0.1 on 1 domain model, score is 100 * (1 - 0.1/1) = 90.0%
    assert "90.0%" in output


def test_get_health_json_data_includes_weights() -> None:
    """Validate that get_health_json_data includes check_weights in JSON output."""
    from tff.core.logs import get_health_json_data

    config = FitnessFunctionsConfig.model_validate({
        "checks": {"layer_integrity": {"enabled": True}},
        "health": {
            "weights": {
                "layer_integrity": 3.0,
            }
        }
    })
    scores = calculate_health_scores([], models_checked=5, config=config, provider="dbt")
    data = get_health_json_data(scores, models_checked=5)
    assert "check_weights" in data
    assert data["check_weights"]["layer_integrity"] == 3.0


