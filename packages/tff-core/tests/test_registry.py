"""Tests for CheckRegistry, CheckDefinition, and granular rule execution."""

from pathlib import Path
import pytest

from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.registry import (
    CheckDefinition,
    CheckRegistry,
    normalize_check_name,
    registry,
    run_model_rule,
)
from tff.core.report import LintFinding
from tff.core.rules.ban_select_star import BanSelectStar
from tff.core.rules.base import Rule, RuleViolation
import tff.dbt.runner as dbt_runner
import tff.dataform.runner as dataform_runner
import tff.sqlmesh.runner as sqlmesh_runner


def test_normalize_check_name() -> None:
    assert normalize_check_name("no_missing_owner") == "nomissingowner"
    assert normalize_check_name("Ban-Select-Star") == "banselectstar"
    assert normalize_check_name(" COLUMN NAMES ") == "columnnames"


def test_check_definition_properties() -> None:
    c1 = CheckDefinition(
        id="test_check",
        label="Test Check",
        category="Test Category",
        scope="model",
        finding_check_id="custom_finding",
        aliases=("alias1", "alias2"),
    )
    assert c1.canonical_id == "test_check"
    assert c1.finding_id == "custom_finding"

    c2 = CheckDefinition(
        id="test_alias_fallback",
        label="Alias Fallback",
        category="Test",
        scope="model",
        aliases=("alias_first",),
    )
    assert c2.finding_id == "alias_first"

    c3 = CheckDefinition(
        id="test_id_fallback",
        label="ID Fallback",
        category="Test",
        scope="dag",
    )
    assert c3.finding_id == "test_id_fallback"


def test_check_definition_get_rule_cls() -> None:
    # Direct rule_cls
    c1 = CheckDefinition(
        id="c1",
        label="C1",
        category="Cat",
        scope="model",
        rule_cls=BanSelectStar,
    )
    assert c1.get_rule_cls() is BanSelectStar

    # Dynamic import via module and class name
    c2 = CheckDefinition(
        id="c2",
        label="C2",
        category="Cat",
        scope="model",
        rule_module="tff.core.rules.ban_select_star",
        rule_class_name="BanSelectStar",
    )
    assert c2.get_rule_cls() is BanSelectStar

    # Neither provided
    c3 = CheckDefinition(id="c3", label="C3", category="Cat", scope="model")
    assert c3.get_rule_cls() is None


def test_check_definition_get_collector_fn() -> None:
    dummy_fn = lambda _m, _c: []  # noqa: E731
    c1 = CheckDefinition(
        id="c1",
        label="C1",
        category="Cat",
        scope="dag",
        collector_fn=dummy_fn,
    )
    assert c1.get_collector_fn() is dummy_fn

    # Dynamic import
    c2 = CheckDefinition(
        id="c2",
        label="C2",
        category="Cat",
        scope="dag",
        collector_module="tff.core.checks.duplicate_ctes",
        collector_func_name="collect_duplicate_cte_findings",
    )
    fn = c2.get_collector_fn()
    assert fn is not None
    assert callable(fn)

    # Neither provided
    c3 = CheckDefinition(id="c3", label="C3", category="Cat", scope="dag")
    assert c3.get_collector_fn() is None


def test_check_definition_is_enabled() -> None:
    cfg = FitnessFunctionsConfig()
    c1 = CheckDefinition(
        id="c1",
        label="C1",
        category="Cat",
        scope="model",
        is_enabled_fn=lambda c, p: p == "dbt",
    )
    assert c1.is_enabled(cfg, provider="dbt") is True
    assert c1.is_enabled(cfg, provider="sqlmesh") is False

    # Default without is_enabled_fn is True
    c2 = CheckDefinition(id="c2", label="C2", category="Cat", scope="model")
    assert c2.is_enabled(cfg) is True


def test_check_definition_run(tmp_path: Path) -> None:
    cfg = FitnessFunctionsConfig()
    cfg.rules.ban_select_star.enabled = True
    set_ff_config(cfg)

    sql_file = tmp_path / "models/marts/test_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM tbl", encoding="utf-8")

    model = ModelRepresentation(
        name="test_model",
        path=str(sql_file),
        dialect="duckdb",
        is_symbolic=False,
    )
    models = {"test_model": model}

    # 1. Model scope with valid rule
    c1 = CheckDefinition(
        id="ban_select_star",
        label="No SELECT *",
        category="CoN",
        scope="model",
        rule_cls=BanSelectStar,
        finding_check_id="banselectstar",
    )
    findings = c1.run(models, cfg)
    assert len(findings) == 1
    assert findings[0].check == "banselectstar"

    # 2. Model scope without rule_cls
    c2 = CheckDefinition(id="empty_model", label="Empty", category="Cat", scope="model")
    assert c2.run(models, cfg) == []

    # 3. DAG scope with valid collector
    c3 = CheckDefinition(
        id="dag_check",
        label="DAG Check",
        category="DAG",
        scope="dag",
        collector_fn=lambda m, c: [
            LintFinding(check="dag_check", severity="error", message="dag violation")
        ],
    )
    findings_dag = c3.run(models, cfg)
    assert len(findings_dag) == 1
    assert findings_dag[0].message == "dag violation"

    # 4. DAG scope without collector
    c4 = CheckDefinition(id="empty_dag", label="Empty", category="Cat", scope="dag")
    assert c4.run(models, cfg) == []

    # 5. Unsupported scope
    c5 = CheckDefinition(id="other", label="Other", category="Cat", scope="other")  # type: ignore[arg-type]
    assert c5.run(models, cfg) == []


def test_run_model_rule_variations(tmp_path: Path) -> None:
    class MockCustomRule(Rule):
        name = "mock_rule"

        def check_model(self, model: ModelRepresentation):
            if model.name == "single_msg":
                return RuleViolation(f"{model.name}: single violation")
            if model.name == "multi_msg":
                return RuleViolation(["multi 1", f"{model.name}: multi 2"])
            return None

    sql_file = tmp_path / "model.sql"
    sql_file.write_text("SELECT 1", encoding="utf-8")

    m_symbolic = ModelRepresentation(name="sym", path=str(sql_file), dialect="duckdb", is_symbolic=True)
    m_external = ModelRepresentation(name="ext", path=str(sql_file), dialect="duckdb", is_external=True)
    m_single = ModelRepresentation(name="single_msg", path=str(sql_file), dialect="duckdb")
    m_multi = ModelRepresentation(name="multi_msg", path=str(sql_file), dialect="duckdb")
    m_clean = ModelRepresentation(name="clean", path=str(sql_file), dialect="duckdb")

    models = {
        "sym": m_symbolic,
        "ext": m_external,
        "single_msg": m_single,
        "multi_msg": m_multi,
        "clean": m_clean,
    }

    findings = run_model_rule(MockCustomRule, models, severity="warning", check_name="custom_check")
    assert len(findings) == 3
    for f in findings:
        assert f.check == "custom_check"
        assert f.severity == "warning"
        assert not f.message.startswith(f"{f.model}: ")


def test_check_registry_lookups_and_errors() -> None:
    reg = CheckRegistry()
    chk = CheckDefinition(
        id="no_missing_owner",
        label="Missing owner",
        category="Quality",
        scope="model",
        finding_check_id="nomissingowner",
        aliases=("owner", "missing_owner"),
    )
    reg.register(chk)

    # Lookup variations
    assert reg.get("no_missing_owner") is chk
    assert reg.get("nomissingowner") is chk
    assert reg.get("No-Missing-Owner") is chk
    assert reg.get("owner") is chk
    assert reg.get("missing_owner") is chk
    assert reg.get("nonexistent") is None

    # get_or_raise
    assert reg.get_or_raise("owner") is chk
    with pytest.raises(ValueError, match="Unknown check or rule: 'nonexistent'"):
        reg.get_or_raise("nonexistent")


def test_check_registry_default_collections() -> None:
    all_chks = registry.all_checks()
    assert len(all_chks) >= 20

    model_rules = registry.model_rules()
    assert len(model_rules) >= 10
    for r in model_rules:
        assert r.scope == "model"

    dag_checks = registry.dag_checks()
    assert len(dag_checks) >= 5
    for d in dag_checks:
        assert d.scope == "dag"

    cfg = FitnessFunctionsConfig()
    cfg.rules.ban_select_star.enabled = True
    assert registry.is_check_enabled(cfg, "ban_select_star") is True
    assert registry.is_check_enabled(cfg, "nonexistent_check") is False


def test_check_registry_resolve_checks() -> None:
    reg = CheckRegistry()
    r1 = CheckDefinition(id="rule1", label="R1", category="C", scope="model", rule_module="m", rule_class_name="c")
    r2 = CheckDefinition(id="rule2", label="R2", category="C", scope="model", rule_module="m", rule_class_name="c")
    d1 = CheckDefinition(id="dag1", label="D1", category="C", scope="dag")
    reg.register(r1)
    reg.register(r2)
    reg.register(d1)

    cfg = FitnessFunctionsConfig()

    # None -> returns all enabled
    assert len(reg.resolve_checks(None, cfg)) == 3

    # "rules" -> expands to all model rules
    resolved_rules = reg.resolve_checks(["rules"], cfg)
    assert set(resolved_rules) == {r1, r2}

    # "sqlmesh" container skipped
    resolved_sqlmesh = reg.resolve_checks(["sqlmesh", "rule1"], cfg)
    assert resolved_sqlmesh == [r1]

    # Specific list without duplicates
    resolved_multi = reg.resolve_checks(["rule1", "rules", "dag1"], cfg)
    assert resolved_multi == [r1, r2, d1]

    # Unknown check raises
    with pytest.raises(ValueError, match="Unknown check or rule: 'bogus'"):
        reg.resolve_checks(["bogus"], cfg)


def test_check_registry_run_checks_helper(tmp_path: Path) -> None:
    reg = CheckRegistry()
    r1 = CheckDefinition(
        id="ban_select_star",
        label="No SELECT *",
        category="CoN",
        scope="model",
        rule_cls=BanSelectStar,
        finding_check_id="banselectstar",
    )
    d1 = CheckDefinition(
        id="custom_dag",
        label="Custom DAG",
        category="DAG",
        scope="dag",
        collector_fn=lambda m, c: [LintFinding(check="custom_dag", severity="error", message="failed")],
    )
    reg.register(r1)
    reg.register(d1)

    cfg = FitnessFunctionsConfig()
    cfg.rules.ban_select_star.enabled = True
    set_ff_config(cfg)

    sql_file = tmp_path / "model.sql"
    sql_file.write_text("SELECT * FROM t", encoding="utf-8")
    model = ModelRepresentation(name="m", path=str(sql_file), dialect="duckdb")
    models = {"m": model}

    # checks=None
    findings, executed = reg.run_checks(models, cfg, checks=None)
    assert len(findings) == 2
    assert executed == ["rules", "custom_dag"]

    # checks specified
    findings, executed = reg.run_checks(models, cfg, checks=["ban_select_star"])
    assert len(findings) == 1
    assert executed == ["ban_select_star"]


def test_check_registry_metadata_dictionaries() -> None:
    labels = registry.get_check_labels()
    assert "ban_select_star" in labels
    assert "banselectstar" in labels

    connascence = registry.get_connascence_categories()
    assert connascence["ban_select_star"] == "Connascence of Name (CoN)"
    assert connascence["banselectstar"] == "Connascence of Name (CoN)"

    categories = registry.get_categories()
    assert "Connascence of Name (CoN)" in categories
    assert "banselectstar" in categories["Connascence of Name (CoN)"]

    proj_level = registry.get_project_level_check_names()
    assert "layer_integrity" in proj_level

    arch_checks = registry.get_architectural_check_names()
    assert "layer_integrity" in arch_checks


def test_dbt_runner_granular_execution(tmp_path: Path) -> None:
    cfg = FitnessFunctionsConfig()
    cfg.rules.ban_select_star.enabled = True
    set_ff_config(cfg)

    sql_file = tmp_path / "model.sql"
    sql_file.write_text("SELECT * FROM t", encoding="utf-8")
    model = ModelRepresentation(name="m", path=str(sql_file), dialect="duckdb")
    models = {"m": model}

    # Test collect_dbt_rules_findings direct call
    rule_findings = dbt_runner.collect_dbt_rules_findings(models)
    assert len(rule_findings) >= 1

    # Test _check_enabled
    assert dbt_runner._check_enabled(cfg, "schema_contracts") is True
    cfg.checks.schema_contracts.enabled = False
    assert dbt_runner._check_enabled(cfg, "schema_contracts") is False
    assert dbt_runner._check_enabled(cfg, "nonexistent") is False
    cfg.checks.schema_contracts.enabled = True

    # Granular check: only ban_select_star
    findings, count, selected = dbt_runner.run_all_checks(
        project_root=tmp_path,
        config=cfg,
        checks=["ban_select_star"],
        models=models,
    )
    assert count == 1
    assert selected == ["ban_select_star"]
    assert len(findings) == 1
    assert findings[0].check == "banselectstar"


def test_dataform_runner_granular_execution(tmp_path: Path) -> None:
    cfg = FitnessFunctionsConfig()
    cfg.rules.ban_select_star.enabled = True
    set_ff_config(cfg)

    sql_file = tmp_path / "model.sqlx"
    sql_file.write_text("SELECT * FROM t", encoding="utf-8")
    model = ModelRepresentation(name="m", path=str(sql_file), dialect="bigquery")
    models = {"m": model}

    # Test collect_dataform_rules_findings direct call
    rule_findings = dataform_runner.collect_dataform_rules_findings(models)
    assert len(rule_findings) >= 1

    # Test _check_enabled
    assert dataform_runner._check_enabled(cfg, "schema_contracts") is True
    cfg.checks.schema_contracts.enabled = False
    assert dataform_runner._check_enabled(cfg, "schema_contracts") is False
    assert dataform_runner._check_enabled(cfg, "nonexistent") is False
    cfg.checks.schema_contracts.enabled = True

    # Granular check: only ban_select_star
    findings, count, selected = dataform_runner.run_all_checks(
        project_root=tmp_path,
        config=cfg,
        checks=["ban_select_star"],
        models=models,
    )
    assert count == 1
    assert selected == ["ban_select_star"]
    assert len(findings) == 1
    assert findings[0].check == "banselectstar"


def test_sqlmesh_runner_granular_execution() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "sqlmesh_minimal_project"
    cfg = FitnessFunctionsConfig()
    set_ff_config(cfg)

    # Test _check_enabled
    assert sqlmesh_runner._check_enabled(cfg, "layer_integrity") is True
    assert sqlmesh_runner._check_enabled(cfg, "nonexistent") is False

    # Granular check: DAG check only (layer_integrity) with automatic context initialization
    findings, count, selected = sqlmesh_runner.run_all_checks(
        project_root=fixture_path,
        checks=["layer_integrity"],
    )
    assert count == 2
    assert selected == ["layer_integrity"]
    assert all(f.check == "layer_integrity" for f in findings)
    assert len(findings) == 1

    from sqlmesh.core.context import Context
    from tff.sqlmesh.loader import FitnessLoader

    context = Context(paths=[str(fixture_path)], loader=FitnessLoader)

    # Granular check: "sqlmesh" container
    findings_sqlmesh, count_s, selected_s = sqlmesh_runner.run_all_checks(
        context=context,
        checks=["sqlmesh"],
    )
    assert count_s == 2
    assert selected_s == ["sqlmesh"]

    # Granular check: "rules" container
    findings_rules, count_r, selected_r = sqlmesh_runner.run_all_checks(
        context=context,
        checks=["rules"],
    )
    assert selected_r == ["rules"]

    # Granular check: model rule + DAG check together
    findings_combo, count_c, selected_c = sqlmesh_runner.run_all_checks(
        context=context,
        checks=["ban_select_star", "layer_integrity"],
    )
    assert selected_c == ["ban_select_star", "layer_integrity"]
    assert any(f.check == "layer_integrity" for f in findings_combo)

    # Granular check: single model rule
    findings_ban, _, selected_ban = sqlmesh_runner.run_all_checks(
        context=context,
        checks=["ban_select_star"],
    )
    assert selected_ban == ["ban_select_star"]
    assert all(f.check == "banselectstar" for f in findings_ban)

    # Unknown check raises ValueError
    with pytest.raises(ValueError, match="Unknown check or rule: 'invalid_rule'"):
        sqlmesh_runner.run_all_checks(
            context=context,
            checks=["invalid_rule"],
        )


def test_sqlmesh_runner_fallback_without_context(tmp_path: Path) -> None:
    cfg = FitnessFunctionsConfig()
    cfg.rules.ban_select_star.enabled = True
    set_ff_config(cfg)

    sql_file = tmp_path / "model.sql"
    sql_file.write_text("SELECT * FROM t", encoding="utf-8")
    model = ModelRepresentation(name="m", path=str(sql_file), dialect="duckdb")
    models = {"m": model}

    # Pass nonexistent project root so context is None, but provide models dict
    findings, count, selected = sqlmesh_runner.run_all_checks(
        project_root=tmp_path / "nonexistent",
        config=cfg,
        checks=["ban_select_star"],
        models=models,
    )
    assert count == 1
    assert selected == ["ban_select_star"]
    assert len(findings) == 1
    assert findings[0].check == "banselectstar"
