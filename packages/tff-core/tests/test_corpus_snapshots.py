"""Corpus snapshot regression test suite for tff across reference projects.

Verifies that rule checks and health calculations produce deterministic results
across dbt, SQLMesh, and Dataform example projects, preventing false-positive
drift or accidental rule regressions.
"""

from __future__ import annotations

from pathlib import Path

from tff.core.adapter import get_adapter
from tff.core.cli import _detect_provider
from tff.core.config import FitnessFunctionsConfig
from tff.core.health import calculate_health_scores
from tff.core.model import ModelRepresentation
from tff.core.registry import CheckDefinition, CheckRegistry
from tff.core.rules.base import Rule, RuleViolation


def _get_example_project(name: str) -> Path:
    # Resolves to repo_root/examples/<name>
    root = Path(__file__).resolve().parents[3]
    project_path = root / "examples" / name
    assert project_path.exists(), f"Example project fixture {name} not found at {project_path}"
    return project_path


def test_dbt_example_corpus_snapshot():
    """Verify that minimal-dbt-project produces consistent, calibrated rule findings."""
    project_path = _get_example_project("minimal-dbt-project")
    provider = _detect_provider(project_path)
    assert provider == "dbt"

    adapter = get_adapter(provider)
    config = FitnessFunctionsConfig()
    findings, models_checked, executed_checks = adapter.run_checks(
        project_root=project_path,
        config=config,
    )

    assert models_checked == 4
    assert len(findings) == 7

    error_findings = [f for f in findings if f.severity == "error"]
    warning_findings = [f for f in findings if f.severity == "warning"]

    assert len(error_findings) == 7
    assert len(warning_findings) == 0

    finding_checks = {f.check for f in findings}
    assert "martmodelnamingconvention" in finding_checks
    assert "nomissingnotnull" in finding_checks
    assert "nomissinguniquevalues" in finding_checks

    # Check mart naming convention specifically caught dim_customers
    naming_violations = [f for f in findings if f.check == "martmodelnamingconvention"]
    assert len(naming_violations) == 1
    assert "dim_customers" in naming_violations[0].model


def test_sqlmesh_example_corpus_snapshot():
    """Verify that minimal-sqlmesh-project catches duplicate CTEs, layer violations, and owner checks."""
    project_path = _get_example_project("minimal-sqlmesh-project")
    provider = _detect_provider(project_path)
    assert provider == "sqlmesh"

    adapter = get_adapter(provider)
    config = FitnessFunctionsConfig()
    findings, models_checked, executed_checks = adapter.run_checks(
        project_root=project_path,
        config=config,
    )

    assert models_checked == 5
    assert len(findings) == 7

    error_findings = [f for f in findings if f.severity == "error"]
    warning_findings = [f for f in findings if f.severity == "warning"]

    assert len(error_findings) == 3
    assert len(warning_findings) == 4

    error_checks = {f.check for f in error_findings}
    assert "banselectstar" in error_checks
    assert "nomissingowner" in error_checks
    assert "layer_integrity" in error_checks

    # Verify duplicate CTEs (Connascence of Algorithm) are flagged with warnings
    dup_cte_findings = [f for f in warning_findings if f.check == "duplicate_ctes"]
    assert len(dup_cte_findings) == 4
    for f in dup_cte_findings:
        assert "Connascence of Algorithm" in f.message


def test_dataform_example_corpus_snapshot():
    """Verify that minimal-dataform-project runs cleanly without false positives."""
    project_path = _get_example_project("minimal-dataform-project")
    provider = _detect_provider(project_path)
    assert provider == "dataform"

    adapter = get_adapter(provider)
    config = FitnessFunctionsConfig()
    findings, models_checked, executed_checks = adapter.run_checks(
        project_root=project_path,
        config=config,
    )

    assert models_checked == 2
    assert len(findings) == 0


def test_health_score_calibration_stability():
    """Verify health score calculations produce calibrated results within bounds."""
    # Dataform project has 0 findings on 2 models -> 100.0 health score
    df_path = _get_example_project("minimal-dataform-project")
    df_adapter = get_adapter("dataform")
    df_config = FitnessFunctionsConfig()
    df_findings, df_count, _ = df_adapter.run_checks(project_root=df_path, config=df_config)
    df_health = calculate_health_scores(df_findings, df_count, config=df_config, provider="dataform")
    assert df_health["overall_score"] == 100.0

    # SQLMesh project has findings -> calibrated score should be strictly between 0 and 100
    sm_path = _get_example_project("minimal-sqlmesh-project")
    sm_adapter = get_adapter("sqlmesh")
    sm_config = FitnessFunctionsConfig()
    sm_findings, sm_count, _ = sm_adapter.run_checks(project_root=sm_path, config=sm_config)
    sm_health = calculate_health_scores(sm_findings, sm_count, config=sm_config, provider="sqlmesh")
    assert 0.0 <= sm_health["overall_score"] < 100.0
    assert len(sm_findings) == 7


def test_rule_maturity_lifecycle_metadata():
    """Verify rule maturity defaults to 'stable' and respects custom maturity declarations."""
    # Default Rule has maturity == "stable"
    class DefaultRule(Rule):
        name = "default_stable_rule"

        def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
            return None

    assert DefaultRule.maturity == "stable"
    dummy_model = ModelRepresentation(name="test_model", path="test.sql", dialect="duckdb")
    assert DefaultRule().check_model(dummy_model) is None

    # Custom experimental rule
    class ExperimentalRule(Rule):
        name = "experimental_syntax_rule"
        maturity = "experimental"

        def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
            return None

    assert ExperimentalRule().check_model(dummy_model) is None

    registry = CheckRegistry()
    def1 = registry.register_rule(DefaultRule)
    assert def1.maturity == "stable"

    def2 = registry.register_rule(ExperimentalRule)
    assert def2.maturity == "experimental"

    # Check direct CheckDefinition instantiation
    cd = CheckDefinition(
        id="custom_deprecated",
        label="Custom Deprecated",
        category="Legacy",
        scope="dag",
        maturity="deprecated",
    )
    assert cd.maturity == "deprecated"
