from pathlib import Path

from sqlmesh_ff.cli import main
from sqlmesh_ff.runner import run_all_checks

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "minimal_project"


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
    
    with patch("sqlmesh_ff.cli.run_all_checks") as mock_run, \
         patch("sqlmesh_ff.cli.render_lint_report") as mock_render:
        mock_run.return_value = ([], 0, [])
        mock_render.return_value = False

        exit_code = main(["lint", "--project", "."])
        assert exit_code == 1


def test_cli_lint_with_group_by():
    from unittest.mock import patch
    
    with patch("sqlmesh_ff.cli.run_all_checks") as mock_run, \
         patch("sqlmesh_ff.cli.render_lint_report") as mock_render:
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
