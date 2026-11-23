"""Tests for configurable severity ('error' | 'warning') across all checks and rules."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from conftest import _make_finding, _make_model
from tff.core.checks.custom_exclusions import collect_custom_exclusion_findings
from tff.core.checks.dependency_graph import collect_dependency_graph_findings
from tff.core.checks.layer_integrity import collect_layer_integrity_findings
from tff.core.checks.materialization_depth import collect_materialization_depth_findings
from tff.core.checks.schema_contracts import collect_schema_contract_findings
from tff.core.config import CheckEnabled, FitnessFunctionsConfig, MetadataRuleConfig
from tff.core.registry import (
    CheckDefinition,
    apply_severity_override,
    registry,
)
from tff.core.rules.sql_complexity import split_complexity_message
from tff.sqlmesh.runner import (
    _run_collector_safely,
    collect_sqlmesh_findings,
    get_executed_checks,
)


@pytest.mark.parametrize(
    "field,value,expected_enabled,expected_severity",
    [
        ("owner", True, True, None),
        ("owner", False, False, None),
        ("owner", {"enabled": True, "severity": "warning"}, True, "warning"),
        ("owner", {"enabled": False, "severity": "warning"}, False, "warning"),
        ("description", {"severity": "warning"}, True, "warning"),
        ("grain", {"enabled": True, "severity": "warning"}, True, "warning"),
        ("grain", CheckEnabled(enabled=False, severity="error"), False, "error"),
        ("not_null", {"enabled": True, "severity": "warning"}, True, "warning"),
        ("unique_values", {"enabled": True, "severity": "error"}, True, "error"),
    ],
)
def test_metadata_rule_config_field_options(
    field: str,
    value: object,
    expected_enabled: bool,
    expected_severity: str | None,
) -> None:
    cfg = MetadataRuleConfig.model_validate({field: value})
    assert cfg.is_field_enabled(field) is expected_enabled
    assert cfg.get_field_severity(field) == expected_severity


@pytest.mark.parametrize(
    "check_id",
    [
        "no_missing_owner",
        "no_missing_description",
        "no_missing_grain",
        "no_missing_not_null",
        "no_missing_unique_values",
        "no_missing_audits",
        "no_missing_table_metadata",
        "no_missing_column_metadata",
    ],
)
def test_metadata_subrules_inherit_group_severity(check_id: str) -> None:
    cfg = FitnessFunctionsConfig.model_validate({"rules": {"metadata": {"severity": "warning"}}})
    check_def = registry.get_or_raise(check_id)
    assert check_def.get_configured_severity(cfg) == "warning"
    assert check_def.get_severity(cfg) == "warning"
    assert check_def.get_configured_severity(None) is None


@pytest.mark.parametrize(
    "rules_payload,check_id,expected",
    [
        (
            {"metadata": {"severity": "warning", "owner": {"enabled": True, "severity": "error"}}},
            "no_missing_owner",
            "error",
        ),
        (
            {"metadata": {"severity": "warning", "owner": {"enabled": True, "severity": "error"}}},
            "no_missing_description",
            "warning",
        ),
        (
            {
                "metadata": {"severity": "error", "owner": {"enabled": True, "severity": "error"}},
                "no_missing_owner": {"severity": "warning"},
            },
            "no_missing_owner",
            "warning",
        ),
    ],
)
def test_metadata_severity_precedence(
    rules_payload: dict, check_id: str, expected: str
) -> None:
    cfg = FitnessFunctionsConfig.model_validate({"rules": rules_payload})
    check_def = registry.get_or_raise(check_id)
    assert check_def.get_severity(cfg) == expected


def test_metadata_inline_disable_and_severity_in_execution() -> None:
    cfg = FitnessFunctionsConfig.model_validate(
        {
            "rules": {
                "metadata": {
                    "enabled": True,
                    "severity": "warning",
                    "owner": {"enabled": True, "severity": "warning"},
                    "description": {"enabled": False, "severity": "error"},
                    "grain": {"enabled": False},
                    "not_null": {"enabled": False},
                    "unique_values": {"enabled": False},
                }
            }
        }
    )
    model = _make_model(name="core.users", path="models/core/users.sql")
    findings, _ = registry.run_checks(
        {"core.users": model},
        cfg,
        checks=["no_missing_owner", "no_missing_description"],
    )
    assert len(findings) == 1
    assert findings[0].check == "nomissingowner"
    assert findings[0].severity == "warning"

    executed = get_executed_checks(cfg, checks=["sqlmesh"])
    assert "nomissingowner" in executed
    assert "nomissingdescription" not in executed
    assert "nomissinggrain" not in executed
    assert "nomissingnotnull" not in executed
    assert "nomissinguniquevalues" not in executed


@pytest.mark.parametrize("configured_severity,expected", [(None, "error"), ("warning", "warning"), ("error", "error")])
def test_layer_integrity_severity(configured_severity: str | None, expected: str) -> None:
    cfg = FitnessFunctionsConfig.model_validate(
        {"checks": {"layer_integrity": {"severity": configured_severity}}}
    )
    models = {
        "stg_users": _make_model(
            name="stg_users",
            path="models/staging/stg_users.sql",
            depends_on={"core_users"},
        ),
        "core_users": _make_model(name="core_users", path="models/core/core_users.sql"),
        "mkt_a": _make_model(
            name="mkt_a",
            path="models/marts/marketing/mkt_a.sql",
            depends_on={"fin_b"},
        ),
        "fin_b": _make_model(name="fin_b", path="models/marts/finance/fin_b.sql"),
    }
    findings = collect_layer_integrity_findings(models, cfg)
    assert len(findings) == 2
    assert all(f.severity == expected for f in findings)


@pytest.mark.parametrize("configured_severity,expected", [(None, "error"), ("warning", "warning"), ("error", "error")])
def test_custom_exclusions_severity(configured_severity: str | None, expected: str) -> None:
    cfg = FitnessFunctionsConfig.model_validate(
        {
            "checks": {
                "custom_exclusions": {
                    "severity": configured_severity,
                    "exclusions": [{"source_layer": "staging", "target_layer": "marts"}],
                }
            }
        }
    )
    models = {
        "stg_a": _make_model(name="stg_a", path="models/staging/stg_a.sql"),
        "mart_b": _make_model(
            name="mart_b",
            path="models/marts/mart_b.sql",
            depends_on={"stg_a"},
        ),
    }
    findings = collect_custom_exclusion_findings(models, cfg)
    assert len(findings) == 1
    assert findings[0].severity == expected


@pytest.mark.parametrize("configured_severity,expected", [(None, "error"), ("warning", "warning"), ("error", "error")])
def test_schema_contracts_severity(
    tmp_path: Path, configured_severity: str | None, expected: str
) -> None:
    ref_sql = tmp_path / "ref.sql"
    mem_sql = tmp_path / "mem.sql"
    ref_sql.write_text("SELECT id, name FROM src", encoding="utf-8")
    mem_sql.write_text("SELECT id FROM src", encoding="utf-8")
    cfg = FitnessFunctionsConfig.model_validate(
        {
            "checks": {
                "schema_contracts": {
                    "severity": configured_severity,
                    "column_parity_groups": [
                        {"reference": "ref.sql", "members": ["mem.sql"]}
                    ],
                }
            }
        }
    )
    cfg._project_root = tmp_path
    findings = collect_schema_contract_findings({}, cfg)
    assert findings
    assert all(f.severity == expected for f in findings)


@pytest.mark.parametrize(
    "configured_severity,expected_fail_sev,expected_warn_sev",
    [
        (None, "error", "warning"),
        ("warning", "warning", "warning"),
        ("error", "error", "error"),
    ],
)
def test_dependency_graph_severity(
    configured_severity: str | None,
    expected_fail_sev: str,
    expected_warn_sev: str,
) -> None:
    cfg = FitnessFunctionsConfig.model_validate(
        {
            "checks": {
                "dependency_graph": {
                    "severity": configured_severity,
                    "fan_out_warn": 1,
                    "fan_out_fail": 2,
                    "fan_in_warn": 1,
                }
            }
        }
    )
    models = {
        "hub_fail": _make_model(name="hub_fail", path="models/core/hub_fail.sql"),
        "hub_warn": _make_model(name="hub_warn", path="models/core/hub_warn.sql"),
        "d1": _make_model(name="d1", path="models/marts/d1.sql", depends_on={"hub_fail", "hub_warn"}),
        "d2": _make_model(name="d2", path="models/marts/d2.sql", depends_on={"hub_fail", "hub_warn"}),
        "d3": _make_model(name="d3", path="models/marts/d3.sql", depends_on={"hub_fail"}),
    }
    findings = collect_dependency_graph_findings(models, cfg)
    fail_out = [f for f in findings if f.model == "hub_fail" and "fan_out=" in f.message]
    warn_out = [f for f in findings if f.model == "hub_warn" and "fan_out=" in f.message]
    warn_in = [f for f in findings if "fan_in=" in f.message]
    assert fail_out and all(f.severity == expected_fail_sev for f in fail_out)
    assert warn_out and all(f.severity == expected_warn_sev for f in warn_out)
    assert warn_in and all(f.severity == expected_warn_sev for f in warn_in)


@pytest.mark.parametrize(
    "configured_severity,expected_fail_sev,expected_warn_sev",
    [
        (None, "error", "warning"),
        ("warning", "warning", "warning"),
        ("error", "error", "error"),
    ],
)
def test_materialization_depth_severity(
    configured_severity: str | None,
    expected_fail_sev: str,
    expected_warn_sev: str,
) -> None:
    cfg = FitnessFunctionsConfig.model_validate(
        {
            "checks": {
                "materialization_depth": {
                    "severity": configured_severity,
                    "max_depth_warn": 1,
                    "max_depth_fail": 2,
                }
            }
        }
    )
    models = {
        "v1": _make_model(name="v1", path="models/staging/v1.sql", materialized="view"),
        "v2": _make_model(
            name="v2", path="models/intermediate/v2.sql", materialized="view", depends_on={"v1"}
        ),
        "v3": _make_model(
            name="v3", path="models/core/v3.sql", materialized="view", depends_on={"v2"}
        ),
    }
    findings = collect_materialization_depth_findings(models, cfg)
    v2_findings = [f for f in findings if f.model == "v2"]
    v3_findings = [f for f in findings if f.model == "v3"]
    assert len(v2_findings) == 1 and v2_findings[0].severity == expected_warn_sev
    assert len(v3_findings) == 1 and v3_findings[0].severity == expected_fail_sev


@pytest.mark.parametrize(
    "severity_override,expected_warn,expected_fail",
    [
        (None, "warning", "error"),
        ("warning", "warning", "warning"),
        ("error", "error", "error"),
    ],
)
def test_sql_complexity_severity_override(
    severity_override: str | None,
    expected_warn: str,
    expected_fail: str,
) -> None:
    msg = "WARN: cte_count=9 (warn>8, fail>12); FAIL: join_count=15 (warn>8, fail>12)"
    parts = split_complexity_message(msg, severity_override=severity_override)  # type: ignore[arg-type]
    assert parts[0][1] == expected_warn
    assert parts[1][1] == expected_fail

    cfg = FitnessFunctionsConfig.model_validate(
        {
            "rules": {
                "sql_complexity": {
                    "severity": severity_override,
                    "thresholds": {"cte_count": [1, 3], "line_count": [1, 100]},
                }
            }
        }
    )
    sql = "WITH a AS (SELECT 1), b AS (SELECT * FROM a) SELECT * FROM b"
    model = _make_model(name="core.complex", path="models/core/complex.sql", query=sql)
    findings, _ = registry.run_checks({"core.complex": model}, cfg, checks=["sql_complexity"])
    assert findings
    assert all(f.severity == expected_warn for f in findings)


def test_custom_dag_check_severity_override_preserves_execution_errors() -> None:
    raw = [
        _make_finding(check="custom_dag", severity="error", message="violation"),
        _make_finding(check="rule_execution_error", severity="error", message="boom"),
    ]
    overridden = apply_severity_override(raw, "warning")
    assert overridden[0].severity == "warning"
    assert overridden[1].severity == "error"
    assert apply_severity_override(raw, None) == raw

    c_def = CheckDefinition(
        id="custom_dag",
        label="Custom DAG",
        category="Custom",
        scope="dag",
        collector_fn=lambda m, c: [_make_finding(check="custom_dag", severity="error", message="v")],
    )
    cfg = FitnessFunctionsConfig.model_validate({"checks": {"custom_dag": {"severity": "warning"}}})
    res = c_def.run({}, cfg)
    assert len(res) == 1
    assert res[0].severity == "warning"


def test_sqlmesh_runner_applies_severity_overrides() -> None:
    cfg = FitnessFunctionsConfig.model_validate(
        {
            "checks": {"layer_integrity": {"severity": "warning"}},
            "rules": {"sql_complexity": {"severity": "error"}},
        }
    )
    dag_res = _run_collector_safely(
        "layer_integrity",
        lambda m, c: [_make_finding(check="layer_integrity", severity="error", message="v")],
        {},
        cfg,
    )
    assert len(dag_res) == 1
    assert dag_res[0].severity == "warning"

    from sqlmesh.core.linter.definition import AnnotatedRuleViolation

    mock_model = SimpleNamespace(
        name="core.m1",
        project="proj",
        kind=SimpleNamespace(is_symbolic=False),
        _path=Path("models/core/m1.sql"),
    )
    mock_rule = SimpleNamespace(name="sqlcomplexity")
    violation = AnnotatedRuleViolation(
        rule=mock_rule,  # type: ignore[arg-type]
        violation_msg="WARN: cte_count=9 (warn>8, fail>12)",
        violation_type="warning",
        model=mock_model,  # type: ignore[arg-type]
    )
    mock_linter = MagicMock()
    mock_linter.enabled = True
    mock_linter.lint_model.return_value = (None, [violation])
    mock_ctx = SimpleNamespace(
        models={"core.m1": mock_model},
        _linters={"proj": mock_linter},
    )
    sqlmesh_findings = collect_sqlmesh_findings(mock_ctx, config=cfg)  # type: ignore[arg-type]
    assert len(sqlmesh_findings) == 1
    assert sqlmesh_findings[0].severity == "error"
