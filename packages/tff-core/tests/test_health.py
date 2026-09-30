"""Tests for project health scoring and reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
import pytest
from rich.console import Console

from conftest import _make_finding, _make_model
from tff.core.config import FitnessFunctionsConfig
from tff.core.health import (
    calculate_health_scores,
    is_check_enabled,
    render_health_report,
)
from tff.core.cli import main


def test_test_factories_and_fixtures(make_finding, make_model) -> None:
    """Verify shared test factories and pytest fixtures."""
    f = make_finding()
    assert f.check == "banselectstar"
    assert f.severity == "error"

    m = make_model()
    assert m.name == "test_model"
    assert m.dialect == "duckdb"

    m2 = _make_model(name="custom_model", path="models/custom.sql")
    assert m2.name == "custom_model"
    assert m2.path == "models/custom.sql"


def _make_config(
    enabled_checks: list[str] | None = None,
    enabled_rules: list[str] | None = None,
    health: dict[str, Any] | None = None,
    **kwargs: Any,
) -> FitnessFunctionsConfig:
    """Build a test FitnessFunctionsConfig with specified checks and rules enabled."""
    all_checks = [
        "layer_integrity",
        "custom_exclusions",
        "schema_contracts",
        "dependency_graph",
        "materialization_depth",
        "duplicate_ctes",
        "connascence_of_value",
        "join_type_parity",
    ]
    all_rules = [
        "ban_select_star",
        "filename_equals_modelname",
        "column_names",
        "column_types",
        "mart_naming",
        "classification_macros",
        "sql_complexity",
        "environment_agnostic_references",
        "metadata",
        "no_positional_group_by",
        "no_positional_order_by",
        "no_positional_group_by_or_order_by",
    ]
    checks_dict = {c: {"enabled": c in (enabled_checks or [])} for c in all_checks}
    rules_dict = {r: {"enabled": r in (enabled_rules or [])} for r in all_rules}
    data: dict[str, Any] = {"checks": checks_dict, "rules": rules_dict, **kwargs}
    if health:
        data["health"] = health
    return FitnessFunctionsConfig.model_validate(data)


@pytest.mark.parametrize(
    "check,provider,metadata_enabled,expected",
    [
        ("layer_integrity", "dbt", True, True),
        ("custom_exclusions", "dbt", True, False),
        ("banselectstar", "dbt", True, True),
        ("nomissingowner", "dbt", True, True),
        ("nomissingdescription", "dbt", True, False),
        ("nomissingowner", "dbt", False, False),
        ("ambiguousorinvalidcolumn", "sqlmesh", True, True),
        ("ambiguousorinvalidcolumn", "dbt", True, False),
    ],
)
def test_is_check_enabled(
    check: str, provider: str, metadata_enabled: bool, expected: bool
) -> None:
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "layer_integrity": {"enabled": True},
            "custom_exclusions": {"enabled": False},
        },
        "rules": {
            "ban_select_star": {"enabled": True},
            "metadata": {
                "enabled": metadata_enabled,
                "owner": True,
                "description": False,
            },
        },
    })
    assert is_check_enabled(config, check, provider) is expected


def test_calculate_health_scores() -> None:
    config = _make_config(
        enabled_checks=["layer_integrity"],
        enabled_rules=["ban_select_star", "filename_equals_modelname"],
    )

    findings = [
        _make_finding(check="banselectstar", severity="error", message="error msg", model="model_a"),
        _make_finding(check="banselectstar", severity="warning", message="warn msg", model="model_b"),
        _make_finding(check="layer_integrity", severity="warning", message="project warn"),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    # banselectstar score: 100 * (1 - (1 + 0.5 * 1) / 10) = 85.0%
    assert scores["check_scores"]["banselectstar"] == 85.0
    # filenameequalsmodelname score: 100.0% (no findings)
    assert scores["check_scores"]["filenameequalsmodelname"] == 100.0
    # layer_integrity score: 50.0% (project level, only warning)
    assert scores["check_scores"]["layer_integrity"] == 50.0

    # overall score: (85 + 100 + 50) / 3 = 78.333%
    assert abs(scores["overall_score"] - 78.333) < 0.01
    assert scores["category_scores"]["Connascence of Name (CoN)"] == 92.5
    assert scores["category_scores"]["Dynamic Coupling & DAG Structure"] == 50.0


def test_render_health_report_smoke() -> None:
    """Smoke test verifying Rich console visual layout for the health report."""
    config = _make_config(
        enabled_checks=["layer_integrity"],
        enabled_rules=["ban_select_star"],
    )
    findings = [
        _make_finding(check="banselectstar", severity="error", message="error msg", model="model_a"),
    ]
    scores = calculate_health_scores(findings, models_checked=5, config=config, provider="dbt")

    console = Console(record=True, width=100)
    render_health_report(
        scores, config, provider="dbt", console=console, duration=1.23, fail_under=98.0
    )

    output = console.export_text()
    assert "PROJECT FITNESS SCORE" in output
    assert "OVERALL HEALTH" in output
    assert "DIMENSION" in output
    assert "Connascence of Name" in output
    assert "DOMAIN BREAKDOWN" in output
    assert "STATUS" in output
    assert "ACTION" in output
    assert "[FAIL: TARGET >= 98.0%]" in output


def test_cli_health_command(tmp_path, monkeypatch) -> None:
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = (
        [
            _make_finding(check="banselectstar", severity="warning", message="warning", model="model_a"),
        ],
        5,
        ["rules"],
    )

    def mock_import_module(name):
        if name == "tff.dbt.runner":
            return mock_runner
        raise ImportError("mock error")

    monkeypatch.setattr("importlib.import_module", mock_import_module)

    try:
        mock_import_module("non_existent")
    except ImportError:
        pass

    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text("""
checks:
  layer_integrity:
    enabled: false
  duplicate_ctes:
    enabled: false
  connascence_of_value:
    enabled: false
  join_type_parity:
    enabled: false
rules:
  ban_select_star:
    enabled: true
""", encoding="utf-8")
    (tmp_path / "dbt_project.yml").write_text("", encoding="utf-8")

    exit_code = main(["health", "--project", str(tmp_path), "--config", str(config_file), "--fail-under", "80.0"])
    assert exit_code == 0

    exit_code_fail = main([
        "health",
        "--project", str(tmp_path),
        "--config", str(config_file),
        "--fail-under", "99.5",
    ])
    assert exit_code_fail == 1


def test_health_edge_cases() -> None:
    config = _make_config(enabled_checks=["layer_integrity"], enabled_rules=["ban_select_star"])

    # 1. Zero enabled checks -> overall_score = 100.0
    scores_empty = calculate_health_scores([], models_checked=5, config=_make_config(), provider="dbt")
    assert scores_empty["overall_score"] == 100.0

    # 2. Check not in all_known_checks added to enabled_checks
    findings_unknown = [
        _make_finding(check="custom_unknown_check", severity="error", message="unknown error", model="model_a"),
    ]
    scores_unknown = calculate_health_scores(findings_unknown, models_checked=5, config=config, provider="dbt")
    assert "custom_unknown_check" in scores_unknown["enabled_checks"]
    assert scores_unknown["category_scores"]["Other Checks"] == 80.0

    # 3. Model with both error and warning -> warning ignored for that model
    findings = [
        _make_finding(check="banselectstar", severity="error", message="error", model="model_a"),
        _make_finding(check="banselectstar", severity="warning", message="warn", model="model_a"),
    ]
    scores = calculate_health_scores(findings, models_checked=5, config=config, provider="dbt")
    assert scores["check_scores"]["banselectstar"] == 80.0

    # 4. Project-level check with error -> 0.0
    findings_project_error = [
        _make_finding(check="layer_integrity", severity="error", message="project error"),
    ]
    scores_project_error = calculate_health_scores(findings_project_error, models_checked=5, config=config, provider="dbt")
    assert scores_project_error["check_scores"]["layer_integrity"] == 0.0

    # 5. models_checked <= 0 -> 100.0
    scores_zero_models = calculate_health_scores(findings, models_checked=0, config=config, provider="dbt")
    assert scores_zero_models["check_scores"]["banselectstar"] == 100.0

    # 6. Score calculations for custom unknown check and severe errors
    findings_red_score = [
        _make_finding(check="banselectstar", severity="error", message="error", model=f"model_{c}")
        for c in ("a", "b", "c", "d")
    ] + [
        _make_finding(check="custom_unknown_check", severity="error", message="unknown error", model="model_a"),
        _make_finding(check="custom_unknown_check", severity="warning", message="unknown warning", model="model_b"),
    ]
    scores_red = calculate_health_scores(findings_red_score, models_checked=5, config=config, provider="dbt")
    assert abs(scores_red["check_scores"]["banselectstar"] - 20.0) < 0.01
    assert abs(scores_red["check_scores"]["custom_unknown_check"] - 70.0) < 0.01


def test_calculate_health_scores_with_scope() -> None:
    config = _make_config(enabled_rules=["ban_select_star"])

    findings = [
        _make_finding(
            check="banselectstar", severity="error", message="err",
            model="model_a", path="models/marts/marketing/model_a.sql",
        ),
        _make_finding(
            check="banselectstar", severity="error", message="err",
            model="model_b", path="models/marts/finance/model_b.sql",
        ),
    ]

    scores = calculate_health_scores(
        findings, models_checked=10, config=config, provider="dbt",
        scope=["models/marts/marketing"],
    )
    assert scores["check_scores"]["banselectstar"] == 0.0
    assert scores["overall_score"] == 0.0


def test_calculate_health_scores_with_scoped_models_count() -> None:
    config = _make_config(enabled_rules=["ban_select_star"])

    findings = [
        _make_finding(
            check="banselectstar", severity="error", message="err",
            model="model_a", path="models/marts/marketing/model_a.sql",
        ),
    ]

    scores = calculate_health_scores(
        findings, models_checked=10, config=config, provider="dbt",
        scope=["models/marts/marketing"],
        scoped_models_count=5,
    )
    assert scores["check_scores"]["banselectstar"] == 80.0
    assert scores["overall_score"] == 80.0


def test_calculate_health_scores_scope_excludes_all() -> None:
    config = _make_config(enabled_rules=["ban_select_star"])

    findings = [
        _make_finding(
            check="banselectstar", severity="error", message="err",
            model="model_a", path="models/marts/finance/model_a.sql",
        ),
    ]

    scores = calculate_health_scores(
        findings, models_checked=10, config=config, provider="dbt",
        scope=["models/marts/marketing"],
    )
    assert scores["check_scores"]["banselectstar"] == 100.0
    assert scores["overall_score"] == 100.0


@pytest.mark.parametrize(
    "path,scope,expected",
    [
        ("models/marts/marketing/foo.sql", ["models/marts/marketing"], True),
        ("models/marts/finance/foo.sql", ["models/marts/marketing"], False),
        ("models/marts", ["models/marts"], True),
        (None, ["models/marts"], False),
        ("models/sources/foo.sql", ["models/marts", "models/sources"], True),
    ],
)
def test_matches_scope_helper(path: str | None, scope: list[str], expected: bool) -> None:
    from tff.core.health import _matches_scope

    assert _matches_scope(path, scope) is expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("models/marts/marketing/model.sql", "models/marts/marketing"),
        ("models/sources/model.sql", "models/sources"),
        (None, "Project-level"),
        ("some/other/path/model.sql", "some/other/path/model.sql"),
        ("models", "models"),
    ],
)
def test_domain_key_helper(path: str | None, expected: str) -> None:
    from tff.core.health import _domain_key

    assert _domain_key(path) == expected


def test_render_health_report_group_by_domain_smoke() -> None:
    """Smoke test verifying domain breakdown rendering and hyperlinks."""
    from tff.core.registry import registry

    config = _make_config(enabled_rules=["ban_select_star", "filename_equals_modelname"])

    findings = [
        _make_finding(
            check="banselectstar", severity="error", message="err A",
            model="model_a", path="models/sources/model_a.sql",
        ),
        _make_finding(
            check="banselectstar", severity="warning", message="warn B",
            model="model_b", path="models/marts/marketing/model_b.sql",
        ),
        _make_finding(
            check="filenameequalsmodelname", severity="error", message="err C",
            model="model_c", path="models/marts/marketing/model_c.sql",
        ),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    console = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console, group_by="domain")
    html = console.export_html(clear=False)
    output = console.export_text()

    assert "Detailed Breakdown by Domain" in output
    assert "models/sources" in output
    assert "models/marts/marketing" in output
    assert "banselectstar" in output
    assert "filenameequalsmodelname" in output

    docs_url = registry.get_docs_url("banselectstar")
    assert docs_url is not None
    assert f'href="{docs_url}"' in html
    assert "https://tff.readthedocs.io" not in output


def test_calculate_health_scores_domain_variations() -> None:
    """Verify domain breakdown logic directly without terminal console rendering."""
    # 1. No findings -> 100%
    config_rule = _make_config(enabled_rules=["ban_select_star"])
    scores_empty = calculate_health_scores([], models_checked=5, config=config_rule, provider="dbt")
    assert scores_empty["overall_score"] == 100.0

    # 2. Project-level finding (path=None)
    config_check = _make_config(enabled_checks=["layer_integrity"])
    findings_proj = [_make_finding("layer_integrity", severity="warning", message="proj warning", path=None)]
    scores_proj = calculate_health_scores(findings_proj, models_checked=5, config=config_check, provider="dbt")
    assert scores_proj["check_scores"]["layer_integrity"] == 50.0

    # 3. Info severity keeps check score at 100%
    findings_info = [_make_finding("layer_integrity", severity="info", message="informational", path=None)]
    scores_info = calculate_health_scores(findings_info, models_checked=5, config=config_check, provider="dbt")
    assert scores_info["check_scores"]["layer_integrity"] == 100.0


def test_cli_health_scope(tmp_path, monkeypatch) -> None:
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = (
        [
            _make_finding(
                check="banselectstar", severity="error", message="err",
                model="model_a", path="models/sources/model_a.sql",
            ),
            _make_finding(
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
        "  join_type_parity:\n    enabled: false\n"
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

    exit_code = main([
        "health",
        "--project", str(tmp_path),
        "--config", str(config_file),
        "--scope", "models/sources",
        "--fail-under", "50.0",
    ])
    assert exit_code == 1


def test_cli_health_group_by_domain(tmp_path, monkeypatch) -> None:
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = (
        [
            _make_finding(
                check="banselectstar", severity="error", message="err",
                model="model_a", path="models/sources/model_a.sql",
            ),
        ],
        5,
        ["banselectstar"],
    )
    monkeypatch.setattr("importlib.import_module", lambda name: mock_runner)

    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text("rules:\n  ban_select_star:\n    enabled: true\n", encoding="utf-8")
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
    config = _make_config(
        enabled_checks=["layer_integrity", "schema_contracts"],
        enabled_rules=["ban_select_star", "column_names"],
        health={
            "weights": {
                "layer_integrity": 3.0,
                "schema_contracts": 2.0,
                "column_names": 0.5,
            }
        },
    )

    findings = [
        _make_finding(check="layer_integrity", severity="warning", message="warn"),
        _make_finding(check="columnnames", severity="error", message="col error", model="model_a"),
        _make_finding(check="banselectstar", severity="error", message="star error 1", model="model_b"),
        _make_finding(check="banselectstar", severity="error", message="star error 2", model="model_c"),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    assert scores["check_weights"]["layer_integrity"] == 3.0
    assert scores["check_weights"]["schema_contracts"] == 2.0
    assert scores["check_weights"]["columnnames"] == 0.5
    assert scores["check_weights"]["banselectstar"] == 1.0

    assert scores["check_scores"]["layer_integrity"] == 50.0
    assert scores["check_scores"]["schema_contracts"] == 100.0
    assert scores["check_scores"]["columnnames"] == 90.0
    assert scores["check_scores"]["banselectstar"] == 80.0

    assert abs(scores["overall_score"] - (475.0 / 6.5)) < 0.001
    assert abs(scores["category_scores"]["Connascence of Name (CoN)"] - (125.0 / 1.5)) < 0.001
    assert scores["category_scores"]["Dynamic Coupling & DAG Structure"] == 50.0
    assert scores["category_scores"]["Connascence of Type (CoT)"] == 100.0


def test_category_weights_and_overrides() -> None:
    config = _make_config(
        enabled_checks=["layer_integrity", "dependency_graph"],
        enabled_rules=["ban_select_star", "filename_equals_modelname"],
        health={
            "weights": {
                "dynamic_coupling": 2.0,
                "connascence_of_name": 0.5,
                "ban_select_star": 4.0,
            }
        },
    )

    findings = [
        _make_finding(check="layer_integrity", severity="warning", message="warn"),
        _make_finding(check="banselectstar", severity="error", message="star error", model="model_a"),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    assert scores["check_weights"]["layer_integrity"] == 2.0
    assert scores["check_weights"]["dependency_graph"] == 2.0
    assert scores["check_weights"]["filenameequalsmodelname"] == 0.5
    assert scores["check_weights"]["banselectstar"] == 4.0

    assert scores["check_scores"]["layer_integrity"] == 50.0
    assert scores["check_scores"]["dependency_graph"] == 100.0
    assert scores["check_scores"]["filenameequalsmodelname"] == 100.0
    assert scores["check_scores"]["banselectstar"] == 90.0

    # Total weight: 2.0 + 2.0 + 4.0 + 0.5 = 8.5
    # Overall: (2*50 + 2*100 + 4*90 + 0.5*100) / 8.5 = 710 / 8.5 = 83.529%
    assert abs(scores["overall_score"] - (710.0 / 8.5)) < 0.001


def test_category_weight_aliases_and_category_weights_field() -> None:
    config = _make_config(
        enabled_checks=["layer_integrity"],
        enabled_rules=["ban_select_star"],
        health={
            "category_weights": {
                "dag": 3.0,
                "name": 2.0,
            }
        },
    )

    findings = [
        _make_finding(check="layer_integrity", severity="warning", message="warn"),
        _make_finding(check="banselectstar", severity="error", message="star error", model="model_a"),
    ]

    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    assert scores["check_weights"]["layer_integrity"] == 3.0
    assert scores["check_weights"]["banselectstar"] == 2.0
    assert scores["overall_score"] == (3.0 * 50.0 + 2.0 * 90.0) / 5.0


def test_weights_edge_cases() -> None:
    from tff.core.health import get_check_weight

    # 1. No health config -> default 1.0
    cfg_empty = _make_config()
    assert get_check_weight("layer_integrity", cfg_empty) == 1.0

    # 2. Unknown check with no category or match -> default 1.0
    cfg_weights = _make_config(
        health={"weights": {"layer_integrity": 5.0, "unknown_category": 2.0}}
    )
    assert get_check_weight("totally_unknown_check_xyz", cfg_weights) == 1.0
    assert get_check_weight("layer_integrity", cfg_weights) == 5.0

    # 3. All weights set to 0.0 -> fallback to unweighted average
    config_zeros = _make_config(
        enabled_checks=["layer_integrity"],
        enabled_rules=["ban_select_star"],
        health={"weights": {"layer_integrity": 0.0, "ban_select_star": 0.0}},
    )
    findings = [
        _make_finding(check="layer_integrity", severity="warning", message="warn"),
        _make_finding(check="banselectstar", severity="error", message="star", model="m1"),
    ]
    scores_zeros = calculate_health_scores(findings, models_checked=10, config=config_zeros, provider="dbt")
    assert scores_zeros["overall_score"] == (50.0 + 90.0) / 2.0
    assert scores_zeros["category_scores"]["Dynamic Coupling & DAG Structure"] == 50.0
    assert scores_zeros["category_scores"]["Connascence of Name (CoN)"] == 90.0


def test_configurable_penalties_project_level() -> None:
    config = _make_config(
        enabled_checks=["layer_integrity"],
        health={
            "penalties": {
                "project_error": 60.0,
                "project_warning": 25.0,
            }
        },
    )

    findings_warn = [_make_finding(check="layer_integrity", severity="warning", message="warn")]
    scores_warn = calculate_health_scores(findings_warn, models_checked=5, config=config, provider="dbt")
    assert scores_warn["check_scores"]["layer_integrity"] == 75.0

    findings_err = [_make_finding(check="layer_integrity", severity="error", message="err")]
    scores_err = calculate_health_scores(findings_err, models_checked=5, config=config, provider="dbt")
    assert scores_err["check_scores"]["layer_integrity"] == 40.0


def test_configurable_penalties_model_level() -> None:
    config = _make_config(
        enabled_rules=["ban_select_star"],
        health={
            "penalties": {
                "error": 2.0,
                "warning": 0.25,
            }
        },
    )

    findings = [
        _make_finding(check="banselectstar", severity="error", message="err", model="model_a"),
        _make_finding(check="banselectstar", severity="warning", message="warn", model="model_b"),
    ]
    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")
    # Score: 100 * (1 - (2.0*1 + 0.25*1)/10) = 100 * (1 - 0.225) = 77.5%
    assert scores["check_scores"]["banselectstar"] == 77.5


def test_nested_penalties_and_check_specific_overrides() -> None:
    config = _make_config(
        enabled_checks=["layer_integrity", "schema_contracts"],
        enabled_rules=["ban_select_star", "column_names"],
        health={
            "penalties": {
                "error": 1.0,
                "warning": 0.5,
                "checks": {
                    "layer_integrity": {"warning": 10.0},
                    "ban_select_star": {"error": 0.5},
                },
            }
        },
    )

    findings = [
        _make_finding(check="layer_integrity", severity="warning", message="warn"),
        _make_finding(check="banselectstar", severity="error", message="err", model="model_a"),
        _make_finding(check="columnnames", severity="error", message="err", model="model_b"),
    ]
    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    assert scores["check_scores"]["layer_integrity"] == 90.0
    assert scores["check_scores"]["banselectstar"] == 95.0
    assert scores["check_scores"]["columnnames"] == 90.0


def test_calculate_health_scores_custom_weights_and_penalties() -> None:
    """Verify weight and penalty resolution directly without console rendering."""
    config = _make_config(
        enabled_checks=["layer_integrity"],
        enabled_rules=["ban_select_star"],
        health={
            "weights": {"layer_integrity": 3.0},
            "penalties": {"warning": 0.1},
        },
    )

    findings = [
        _make_finding(check="layer_integrity", severity="warning", message="w"),
        _make_finding(check="banselectstar", severity="warning", message="w", model="m1", path="models/sources/m1.sql"),
    ]
    scores = calculate_health_scores(findings, models_checked=10, config=config, provider="dbt")

    assert scores["check_weights"]["layer_integrity"] == 3.0
    assert scores["check_weights"]["banselectstar"] == 1.0

    scores_scoped = calculate_health_scores(
        findings, models_checked=10, config=config, provider="dbt", scope=["models/sources"]
    )
    assert scores_scoped["check_scores"]["banselectstar"] == 90.0


def test_get_health_json_data_includes_weights() -> None:
    from tff.core.logs import get_health_json_data

    config = _make_config(
        enabled_checks=["layer_integrity"],
        health={"weights": {"layer_integrity": 3.0}},
    )
    scores = calculate_health_scores([], models_checked=5, config=config, provider="dbt")
    data = get_health_json_data(scores, models_checked=5)
    assert "check_weights" in data
    assert data["check_weights"]["layer_integrity"] == 3.0


@pytest.mark.parametrize(
    "icon,check,label,weight_str,disabled,expected_plain,has_link,is_dim",
    [
        (
            "[green]✔[/green]",
            "banselectstar",
            "No SELECT *",
            " · weight: 2",
            False,
            "  ✔ No SELECT * (banselectstar · weight: 2)",
            True,
            False,
        ),
        (
            "[red]✘[/red]",
            "custom_check",
            "Custom Check",
            "",
            False,
            "  ✘ Custom Check (custom_check)",
            False,
            False,
        ),
        (
            "-",
            "banselectstar",
            "No SELECT *",
            "",
            True,
            "  - No SELECT * (banselectstar)",
            True,
            True,
        ),
        (
            "-",
            "unknown_check",
            "Unknown Check",
            "",
            True,
            "  - Unknown Check (unknown_check)",
            False,
            True,
        ),
    ],
)
def test_format_health_check_desc(
    icon: str,
    check: str,
    label: str,
    weight_str: str,
    disabled: bool,
    expected_plain: str,
    has_link: bool,
    is_dim: bool,
) -> None:
    from tff.core.health import _format_health_check_desc
    from tff.core.registry import registry

    desc = _format_health_check_desc(
        icon, check, label, weight_str=weight_str, disabled=disabled
    )
    assert desc.plain == expected_plain
    styles = [str(span.style) for span in desc.spans]

    if has_link:
        docs_url = registry.get_docs_url(check)
        assert docs_url is not None
        assert any(f"link {docs_url}" in s for s in styles)
    else:
        assert not any("link" in s for s in styles)

    if is_dim:
        assert any("dim" in s for s in styles)


def test_render_health_report_verbose_flag() -> None:
    """Verify that verbose=False collapses passing/disabled checks and verbose=True expands them."""
    config = FitnessFunctionsConfig.model_validate({
        "rules": {
            "ban_select_star": {"enabled": True},
            "filename_equals_modelname": {"enabled": False},
            "metadata": {"enabled": True, "owner": True, "description": True},
        },
    })
    findings = [
        _make_finding(check="banselectstar", severity="error", message="err", model="m1"),
        _make_finding(check="nomissingowner", severity="warning", message="warn", model="m2"),
    ]
    scores = calculate_health_scores(findings, models_checked=5, config=config, provider="dbt")

    # 1. Default (verbose=False)
    console_default = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console_default, verbose=False)
    output_default = console_default.export_text()

    assert "Use --verbose to expand all passing and disabled checks." in output_default
    assert "checks disabled" not in output_default
    assert "DIMENSION" in output_default
    assert "DOMAIN BREAKDOWN" in output_default

    # 2. Verbose (verbose=True)
    console_verbose = Console(record=True, width=120)
    render_health_report(scores, config, provider="dbt", console=console_verbose, verbose=True)
    output_verbose = console_verbose.export_text()

    assert "Use --verbose to expand all passing and disabled checks." not in output_verbose
    assert "nomissingowner" in output_verbose
    assert "nomissingdescription" in output_verbose
    assert "1 warning" in output_verbose


def test_cli_health_verbose_flag(tmp_path, monkeypatch) -> None:
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 5, ["rules"])
    monkeypatch.setattr("importlib.import_module", lambda name: mock_runner)

    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text("rules:\n  ban_select_star:\n    enabled: true\n", encoding="utf-8")
    (tmp_path / "dbt_project.yml").write_text("", encoding="utf-8")

    exit_code_verbose = main(["health", "--project", str(tmp_path), "--config", str(config_file), "--verbose"])
    assert exit_code_verbose == 0

    exit_code_v = main(["health", "--project", str(tmp_path), "--config", str(config_file), "-v"])
    assert exit_code_v == 0


@pytest.mark.parametrize(
    "check,count,expected",
    [
        ("duplicate_ctes", 1, "Refactor 1 duplicate CTE"),
        ("duplicate_ctes", 2, "Refactor 2 duplicate CTEs"),
        ("join_type_parity", 1, "Align data types across 1 JOIN condition"),
        ("join_type_parity", 3, "Align data types across 3 JOIN conditions"),
        ("nomissingowner", 1, "Add missing contract metadata to 1 model"),
        ("nomissingowner", 2, "Add missing contract metadata to 2 models"),
        ("banselectstar", 1, "Replace 1 wildcard SELECT * query"),
        ("banselectstar", 2, "Replace 2 wildcard SELECT * queries"),
        ("layer_integrity", 1, "Fix 1 layer integrity violation"),
        ("layer_integrity", 2, "Fix 2 layer integrity violations"),
        ("nopositionalgroupby", 1, "Replace 1 positional GROUP BY reference"),
        ("nopositionalgroupby", 2, "Replace 2 positional GROUP BY references"),
        ("nopositionalorderby", 1, "Replace 1 positional ORDER BY reference"),
        ("nopositionalorderby", 2, "Replace 2 positional ORDER BY references"),
    ],
)
def test_get_action_phrase(check: str, count: int, expected: str) -> None:
    from tff.core.health import _get_action_phrase

    assert _get_action_phrase(check, count) == expected


def test_nonexistent_project_root_health_report() -> None:
    """Nonexistent project_root does not raise and continues cleanly."""
    config = _make_config(enabled_rules=["ban_select_star"])
    findings = [
        _make_finding(check="banselectstar", severity="error", message="err", model="m1", path="models/core/m1.sql"),
    ]
    scores = calculate_health_scores(findings, models_checked=1, config=config, provider="dbt")
    scores["check_weights"] = {c: 0.0 for c in scores["enabled_checks"]}
    console = Console(record=True, width=120)
    render_health_report(
        scores,
        config,
        provider="dbt",
        console=console,
        project_root=Path("/nonexistent_dir_tff_test"),
    )
    output = console.export_text()
    assert "PROJECT FITNESS SCORE" in output
