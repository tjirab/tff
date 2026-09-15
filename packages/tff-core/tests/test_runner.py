from pathlib import Path

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

