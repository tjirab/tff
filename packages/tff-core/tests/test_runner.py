from pathlib import Path

from conftest import _make_model
from tff.sqlmesh.cli import main
from tff.sqlmesh.runner import run_all_checks

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "sqlmesh_minimal_project"


def test_run_all_checks_integration():
    findings, models_checked, selected = run_all_checks(
        project_root=FIXTURE_PATH
    )

    # 2 models in the project
    assert models_checked == 2
    assert "layer_integrity" in selected

    # Should find one layer_integrity violation: src_model depending on violating_model
    layer_integrity_findings = [
        f for f in findings if f.check == "layer_integrity"
    ]
    assert len(layer_integrity_findings) == 1
    finding = layer_integrity_findings[0]
    assert finding.model == "sqlmesh_example.src_model"
    assert "downstream layer" in finding.message


def test_cli_lint_fails():
    from unittest.mock import patch
    
    with patch("tff.sqlmesh.cli.run_all_checks") as mock_run, \
         patch("tff.sqlmesh.cli.render_lint_report") as mock_render:
        mock_run.return_value = ([], 0, [])
        mock_render.return_value = False

        exit_code = main(["lint", "--project", "."])
        assert exit_code == 1


def test_cli_lint_with_group_by():
    from unittest.mock import patch
    
    with patch("tff.sqlmesh.cli.run_all_checks") as mock_run, \
         patch("tff.sqlmesh.cli.render_lint_report") as mock_render:
        mock_run.return_value = ([], 0, [])
        mock_render.return_value = True

        exit_code = main(["lint", "--project", ".", "--group-by", "model"])
        assert exit_code == 0
        
        mock_render.assert_called_with(
            [],
            models_checked=0,
            executed_checks=[],
            fail_level="error",
            group_by="model",
        )


def test_collect_sqlmesh_findings_severities():
    from unittest.mock import MagicMock
    from sqlmesh.core.linter.definition import AnnotatedRuleViolation
    from tff.core.config import FitnessFunctionsConfig
    from tff.sqlmesh.runner import collect_sqlmesh_findings

    mock_context = MagicMock()
    mock_model = MagicMock()
    mock_model.name = "test_model"
    mock_model.project = "default"
    mock_model.kind.is_symbolic = False
    mock_model._path = Path("models/test_model.sql")
    mock_context.models = {"test_model": mock_model}

    mock_linter = MagicMock()
    mock_linter.enabled = True
    mock_context._linters = {"default": mock_linter}

    mock_rule_complexity = MagicMock()
    mock_rule_complexity.name = "sqlcomplexity"

    mock_rule_other = MagicMock()
    mock_rule_other.name = "ban_select_star"

    v_complexity = AnnotatedRuleViolation(
        rule=mock_rule_complexity,
        violation_msg="WARN: cte_count=9 (warn>8, fail>12); FAIL: line_count=500 (warn>250, fail>400); other_metric=1",
        model=mock_model,
        violation_type="error",
    )
    v_other = AnnotatedRuleViolation(
        rule=mock_rule_other,
        violation_msg="SELECT * is banned",
        model=mock_model,
        violation_type="error",
    )
    mock_linter.lint_model.return_value = (True, [v_complexity, v_other])

    # Case 1: Config passed in, ban_select_star overridden to warning
    cfg = FitnessFunctionsConfig()
    cfg.rules.ban_select_star.severity = "warning"

    findings = collect_sqlmesh_findings(mock_context, config=cfg)
    assert len(findings) == 4

    # sqlcomplexity WARN -> warning
    assert findings[0].check == "sqlcomplexity"
    assert findings[0].severity == "warning"
    assert "WARN: cte_count=9" in findings[0].message

    # sqlcomplexity FAIL -> error
    assert findings[1].check == "sqlcomplexity"
    assert findings[1].severity == "error"
    assert "FAIL: line_count=500" in findings[1].message

    # sqlcomplexity other -> rule_severity ("error")
    assert findings[2].check == "sqlcomplexity"
    assert findings[2].severity == "error"
    assert "other_metric=1" in findings[2].message

    # ban_select_star -> configured warning
    assert findings[3].check == "ban_select_star"
    assert findings[3].severity == "warning"

    # Case 2: Config resolved from context.loader._ff_config
    mock_context.loader._ff_config = cfg
    findings_loader = collect_sqlmesh_findings(mock_context, config=None)
    assert len(findings_loader) == 4


def test_collect_sqlmesh_findings_coordinates():
    from unittest.mock import MagicMock
    from sqlmesh.core.linter.definition import AnnotatedRuleViolation
    from sqlmesh.core.linter.rule import Position, Range
    from tff.sqlmesh.runner import collect_sqlmesh_findings

    mock_context = MagicMock()
    mock_model = MagicMock()
    mock_model.name = "coords_model"
    mock_model.project = "default"
    mock_model.kind.is_symbolic = False
    mock_model._path = Path("models/coords_model.sql")
    mock_context.models = {"coords_model": mock_model}

    mock_linter = MagicMock()
    mock_linter.enabled = True
    mock_context._linters = {"default": mock_linter}

    mock_rule = MagicMock()
    mock_rule.name = "ban_select_star"

    v_range = Range(start=Position(line=10, character=2), end=Position(line=10, character=15))
    v = AnnotatedRuleViolation(
        rule=mock_rule,
        violation_msg="coords_model: SELECT * is banned",
        model=mock_model,
        violation_type="error",
        violation_range=v_range,
    )
    mock_linter.lint_model.return_value = (True, [v])

    findings = collect_sqlmesh_findings(mock_context)
    assert len(findings) == 1
    assert findings[0].line == 10
    assert findings[0].col == 2
    assert findings[0].end_line == 10
    assert findings[0].end_col == 15


def test_sqlmesh_runner_and_adapter_propagate_chunk_size() -> None:
    from unittest.mock import patch, MagicMock
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.registry import CheckDefinition
    from tff.sqlmesh.adapter import SQLMeshAdapter

    models = {
        "m1": _make_model(name="m1", path="models/m1.sql", dialect="duckdb"),
    }
    cfg = FitnessFunctionsConfig()

    # 1. run_all_checks passes chunk_size to c_def.run
    mock_cdef = MagicMock(spec=CheckDefinition)
    mock_cdef.id = "ban_select_star"
    mock_cdef.scope = "model"
    mock_cdef.run.return_value = []

    with patch("tff.core.registry.CheckRegistry.get", return_value=mock_cdef):
        findings, count, sel = run_all_checks(
            models=models,
            config=cfg,
            checks=["ban_select_star"],
            chunk_size=11,
        )
        assert findings == []
        mock_cdef.run.assert_called_once_with(
            models,
            cfg,
            scoped_models=None,
            chunk_size=11,
        )

    # 2. SQLMeshAdapter.run_checks passes chunk_size to run_all_checks
    adapter = SQLMeshAdapter()
    with patch("tff.sqlmesh.runner.run_all_checks", return_value=([], 1, ["rules"])) as mock_run_all:
        findings, count, sel = adapter.run_checks(
            project_root=Path.cwd(),
            config=cfg,
            models=models,
            chunk_size=13,
        )
        assert findings == []
        assert count == 1
        assert sel == ["rules"]
        assert mock_run_all.call_args.kwargs.get("chunk_size") == 13


def test_collect_findings_error_isolation_and_scoping() -> None:
    from unittest.mock import MagicMock, patch
    from conftest import _make_finding
    from tff.core.config import FitnessFunctionsConfig
    from tff.sqlmesh.runner import collect_findings, run_all_checks

    cfg = FitnessFunctionsConfig()
    models = {
        "db.m1": _make_model(name="db.m1", path="models/m1.sql", dialect="duckdb"),
        "db.m2": _make_model(name="db.m2", path="models/m2.sql", dialect="duckdb"),
    }

    def failing_collector(_models, _cfg):
        raise RuntimeError("boom in collector")

    def passing_collector(_models, _cfg):
        return [
            _make_finding(check="passing_check", severity="error", model="db.m1", message="ok1"),
            _make_finding(check="passing_check", severity="error", model="db.m2", message="ok2"),
        ]

    with patch.dict(
        "tff.sqlmesh.runner.CHECK_COLLECTORS",
        {"crashing_dag": failing_collector, "passing_dag": passing_collector},
        clear=True,
    ), patch("tff.sqlmesh.runner._check_enabled", return_value=True):
        # 1. Dict context with scoped_models
        findings = collect_findings(models, cfg, scoped_models={"db.m1"})
        err_findings = [f for f in findings if f.check == "rule_execution_error"]
        assert len(err_findings) == 1
        assert err_findings[0].severity == "warning"
        assert "Check 'crashing_dag' failed with RuntimeError: boom in collector" in err_findings[0].message

        pass_findings = [f for f in findings if f.check == "passing_check"]
        assert len(pass_findings) == 1
        assert pass_findings[0].model == "db.m1"

        # 2. SQLMesh Context object without scoped_models
        mock_ctx = MagicMock()
        mock_ctx.models = {}
        mock_ctx._linters = {}
        findings_ctx = collect_findings(mock_ctx, cfg)
        assert any(f.check == "rule_execution_error" for f in findings_ctx)
        assert len([f for f in findings_ctx if f.check == "passing_check"]) == 2

        # 3. run_all_checks with checks=None and checks=["layer_integrity"]
        findings_all, _, _ = run_all_checks(models=models, config=cfg, scoped_models={"db.m1"})
        assert any(f.check == "rule_execution_error" for f in findings_all)

    with patch(
        "tff.core.registry.CheckDefinition.get_collector_fn",
        return_value=failing_collector,
    ):
        findings_chk, _, _ = run_all_checks(
            models=models, config=cfg, checks=["layer_integrity"]
        )
        assert len(findings_chk) == 1
        assert findings_chk[0].check == "rule_execution_error"


def test_get_executed_checks_includes_all_rules_and_plugins() -> None:
    from tff.core.config import ColumnTypeRuleEntry, FitnessFunctionsConfig
    from tff.core.registry import CheckRegistry
    from tff.core.rules.base import Rule
    from tff.sqlmesh.runner import get_executed_checks

    class CustomSqlmeshPluginRule(Rule):
        name = "custom_sqlmesh_plugin"

        def check_model(self, model):
            return None

    reg = CheckRegistry.get_default()
    reg.register_rule(CustomSqlmeshPluginRule, id="custom_sqlmesh_plugin")
    try:
        assert reg.get("custom_sqlmesh_plugin") in reg.get_all_checks()

        cfg = FitnessFunctionsConfig()
        cfg.rules.column_names.enabled = True
        cfg.rules.column_names.replacements = {"old_col": "new_col"}
        cfg.rules.column_types.enabled = True
        cfg.rules.column_types.rules = [
            ColumnTypeRuleEntry(name="id_text", pattern="_id$", data_type="text")
        ]
        cfg.rules.classification_macros.enabled = True

        executed = get_executed_checks(cfg)
        assert "columnnames" in executed
        assert "columntypes" in executed
        assert "classificationmacros" in executed
        assert "custom_sqlmesh_plugin" in executed
        assert "layer_integrity" in executed

        # Explicit checks list
        explicit = get_executed_checks(cfg, checks=["layer_integrity"])
        assert explicit == ["layer_integrity"]
    finally:
        reg.unregister("custom_sqlmesh_plugin")



