"""Unit tests verifying per-model error isolation and contextual diagnostics (Issue #248)."""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from tff.core.checks.custom_exclusions import collect_custom_exclusion_findings
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.parallel import (
    _create_rule_execution_error_finding,
    precompute_model_asts,
    run_parallel_model_rule,
)
from tff.core.registry import CheckDefinition, CheckRegistry
from tff.core.report import (
    CHECK_LABELS,
    _summary_check_names,
    render_lint_report,
)
from tff.core.rules.base import Rule, RuleViolation


class FlakyRule(Rule):
    """Rule that intentionally crashes on a specific model."""

    name = "flaky_rule"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        if model.name == "model_broken":
            raise RuntimeError("AST parsing failed on invalid syntax")
        if model.name == "model_violating":
            return RuleViolation(violation_msg=f"{model.name}: violation found")
        return None


class BrokenInitRule(Rule):
    """Rule whose __init__ fails unexpectedly."""

    name = "broken_init"

    def __init__(self, config=None):
        super().__init__(config=config)
        raise ValueError("Failed to initialize rule dependencies")

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        return None


def test_create_rule_execution_error_finding_formatting():
    """Verify attributes and fallback message of _create_rule_execution_error_finding."""
    model = ModelRepresentation(name="my_model", path="models/my_model.sql", dialect="duckdb")
    exc = ValueError("Regex recursion error")

    finding = _create_rule_execution_error_finding(model, "test_rule", exc)
    assert finding.check == "rule_execution_error"
    assert finding.severity == "error"
    assert finding.model == "my_model"
    assert finding.path == "models/my_model.sql"
    assert "Rule 'test_rule' failed to evaluate: Regex recursion error" in finding.message

    # Empty exception message fallback to class name
    empty_exc = Exception("")
    finding_empty = _create_rule_execution_error_finding(model, "test_rule", empty_exc)
    assert "Rule 'test_rule' failed to evaluate: Exception" in finding_empty.message


def test_run_parallel_model_rule_isolates_single_model_crash_sequential():
    """A single failing model does not prevent other models from being checked in sequential mode."""
    models = [
        ModelRepresentation(name="model_ok", path="models/ok.sql", dialect="duckdb"),
        ModelRepresentation(name="model_broken", path="models/broken.sql", dialect="duckdb"),
        ModelRepresentation(name="model_violating", path="models/violating.sql", dialect="duckdb"),
    ]

    findings = run_parallel_model_rule(
        FlakyRule,
        models,
        severity="error",
        check_name="flaky_rule",
        max_workers=1,
    )

    assert len(findings) == 2

    # Finding 1: Diagnostic error for broken model
    error_finding = next(f for f in findings if f.model == "model_broken")
    assert error_finding.check == "rule_execution_error"
    assert error_finding.severity == "error"
    assert "Rule 'flaky_rule' failed to evaluate: AST parsing failed on invalid syntax" in error_finding.message
    assert error_finding.path == "models/broken.sql"

    # Finding 2: Standard rule violation for model_violating
    violation_finding = next(f for f in findings if f.model == "model_violating")
    assert violation_finding.check == "flaky_rule"
    assert violation_finding.severity == "error"
    assert "violation found" in violation_finding.message


def test_run_parallel_model_rule_isolates_single_model_crash_parallel():
    """A single failing model does not prevent other models from being checked in parallel threadpool."""
    # Create > 20 models to trigger parallel ThreadPoolExecutor path
    models = [
        ModelRepresentation(name=f"model_{i}", path=f"models/{i}.sql", dialect="duckdb")
        for i in range(25)
    ]
    models.append(ModelRepresentation(name="model_broken", path="models/broken.sql", dialect="duckdb"))
    models.append(ModelRepresentation(name="model_violating", path="models/violating.sql", dialect="duckdb"))

    findings = run_parallel_model_rule(
        FlakyRule,
        models,
        severity="error",
        check_name="flaky_rule",
        max_workers=4,
    )

    assert len(findings) == 2
    broken = next((f for f in findings if f.model == "model_broken"), None)
    assert broken is not None
    assert broken.check == "rule_execution_error"
    assert "flaky_rule" in broken.message

    violating = next((f for f in findings if f.model == "model_violating"), None)
    assert violating is not None
    assert violating.check == "flaky_rule"


def test_run_parallel_model_rule_instantiation_failure():
    """When a rule cannot be instantiated, all eligible models receive execution error findings."""
    models = [
        ModelRepresentation(name="m1", path="models/m1.sql", dialect="duckdb"),
        ModelRepresentation(name="m2", path="models/m2.sql", dialect="duckdb"),
    ]

    findings = run_parallel_model_rule(
        BrokenInitRule,
        models,
        severity="error",
        check_name="broken_init",
        max_workers=1,
    )

    assert len(findings) == 2
    for f in findings:
        assert f.check == "rule_execution_error"
        assert "Failed to initialize rule dependencies" in f.message
    assert BrokenInitRule.check_model(None, None) is None


def test_check_registry_run_checks_isolates_failing_check_sequential():
    """CheckRegistry.run_checks catches unexpected exceptions in a check and runs remaining checks."""
    reg = CheckRegistry()

    def passing_collector(models, config):
        return []

    def crashing_collector(models, config):
        raise RuntimeError("Database connection timed out")

    reg.register(
        CheckDefinition(
            id="passing_check",
            label="Passing Check",
            category="Quality",
            scope="dag",
            collector_fn=passing_collector,
        )
    )
    reg.register(
        CheckDefinition(
            id="crashing_check",
            label="Crashing Check",
            category="Quality",
            scope="dag",
            collector_fn=crashing_collector,
        )
    )

    config = FitnessFunctionsConfig()
    models = {"m1": ModelRepresentation(name="m1", path="models/m1.sql", dialect="duckdb")}

    findings, executed = reg.run_checks(
        models=models,
        config=config,
        checks=["passing_check", "crashing_check"],
        max_workers=1,
    )

    assert len(findings) == 1
    assert findings[0].check == "rule_execution_error"
    assert findings[0].model == "project"
    assert "Check 'crashing_check' failed to execute: Database connection timed out" in findings[0].message
    assert executed == ["passing_check", "crashing_check"]


def test_check_registry_run_checks_isolates_failing_check_parallel():
    """CheckRegistry.run_checks catches unexpected exceptions in parallel threadpool."""
    reg = CheckRegistry()

    def passing_collector(models, config):
        return []

    def crashing_collector(models, config):
        raise RuntimeError("Database connection timed out")

    reg.register(
        CheckDefinition(
            id="passing_check",
            label="Passing Check",
            category="Quality",
            scope="dag",
            collector_fn=passing_collector,
        )
    )
    reg.register(
        CheckDefinition(
            id="crashing_check",
            label="Crashing Check",
            category="Quality",
            scope="dag",
            collector_fn=crashing_collector,
        )
    )

    config = FitnessFunctionsConfig()
    models = {"m1": ModelRepresentation(name="m1", path="models/m1.sql", dialect="duckdb")}

    findings, executed = reg.run_checks(
        models=models,
        config=config,
        checks=["passing_check", "crashing_check"],
        max_workers=2,
    )

    assert len(findings) == 1
    assert findings[0].check == "rule_execution_error"
    assert "Check 'crashing_check' failed to execute: Database connection timed out" in findings[0].message


def test_custom_exclusions_isolates_model_error():
    """Unexpected exception in CustomExclusionsChecker produces diagnostic finding and continues."""
    models = {
        "m_ok": ModelRepresentation(name="m_ok", path="models/ok.sql", dialect="duckdb"),
        "m_fail": ModelRepresentation(name="m_fail", path="models/fail.sql", dialect="duckdb"),
    }
    config = FitnessFunctionsConfig()

    with patch("tff.core.checks.custom_exclusions.CustomExclusionsChecker") as mock_checker_cls:
        mock_checker = MagicMock()
        def check_model_side_effect(m):
            if m.name == "m_fail":
                raise RuntimeError("Graph traversal cycle")
            return ["Model 'm_ok' violates rule"]

        mock_checker.check_model.side_effect = check_model_side_effect
        mock_checker_cls.return_value = mock_checker

        findings = collect_custom_exclusion_findings(models, config)

    assert len(findings) == 2
    ok_finding = next(f for f in findings if f.model == "m_ok")
    assert ok_finding.check == "custom_exclusions"

    fail_finding = next(f for f in findings if f.model == "m_fail")
    assert fail_finding.check == "rule_execution_error"
    assert "Rule 'custom_exclusions' failed to evaluate: Graph traversal cycle" in fail_finding.message


def test_precompute_model_asts_handles_read_sql_error(tmp_path: Path):
    """If reading a model SQL file raises an OSError, precompute_model_asts does not crash."""
    m_bad = ModelRepresentation(name="bad_model", path=str(tmp_path / "nonexistent.sql"), dialect="duckdb")
    models = {"bad_model": m_bad}

    with patch("tff.core.parallel.read_model_sql", side_effect=OSError("File corrupted")):
        precompute_model_asts(models, project_root=tmp_path)

    assert m_bad.expression is None


def test_report_includes_rule_execution_error_in_summary_and_labels():
    """Verify that rule_execution_error has a human-readable label and is listed in summary."""
    assert CHECK_LABELS.get("rule_execution_error") == "Rule execution error"

    by_check = {"rule_execution_error": {"error": 1, "warning": 0}}
    names = _summary_check_names(executed_checks=["rules"], by_check=by_check)
    assert "rule_execution_error" in names

    # Render report to string console
    finding = _create_rule_execution_error_finding(
        ModelRepresentation(name="orders", path="models/orders.sql", dialect="duckdb"),
        "ban_select_star",
        RuntimeError("Invalid AST token"),
    )
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True, width=120)

    passed = render_lint_report(
        [finding],
        models_checked=1,
        executed_checks=["rules"],
        console=console,
    )
    assert not passed
    rendered = buf.getvalue()
    assert "Rule execution error" in rendered
    assert "orders" in rendered
    assert "Rule 'ban_select_star' failed to evaluate: Invalid AST token" in rendered
