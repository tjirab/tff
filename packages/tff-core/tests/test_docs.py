from pathlib import Path
from unittest.mock import MagicMock, patch

from tff.core.cli import main
from tff.core.docs import generate_docs_dashboard


@patch("tff.core.cli._get_runner")
@patch("tff.dbt.manifest.load_dbt_models")
@patch("tff.core.docs.collect_stats")
@patch("tff.core.docs.save_log")
def test_generate_docs_dashboard_dbt(
    mock_save_log,
    mock_collect_stats,
    mock_load_dbt_models,
    mock_get_runner,
    tmp_path: Path
):
    # Setup mock data for dbt runner
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 2, ["rules"])
    mock_get_runner.return_value = mock_runner

    # Setup mock models
    from tff.core.model import ModelRepresentation
    mock_model_1 = ModelRepresentation(
        name="model_1",
        path=str(tmp_path / "models/model_1.sql"),
        dialect="duckdb",
        materialized="table",
        depends_on=set()
    )
    mock_model_2 = ModelRepresentation(
        name="model_2",
        path=str(tmp_path / "models/model_2.sql"),
        dialect="duckdb",
        materialized="view",
        depends_on={"model.my_project.model_1"}
    )
    
    # Ensure they have paths and directories created so model_path_relative handles it
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models/model_1.sql").touch()
    (tmp_path / "models/model_2.sql").touch()
    (tmp_path / "fitness_functions.yaml").touch()

    mock_load_dbt_models.return_value = {
        "model.my_project.model_1": mock_model_1,
        "model.my_project.model_2": mock_model_2,
    }

    # Mock history
    mock_collect_stats.return_value = [
        {"date": "2026-08-30", "health_score": 100.0, "errors_count": 0, "warnings_count": 0}
    ]

    # Generate
    output_path = tmp_path / "custom_report.html"
    result_path = generate_docs_dashboard(
        project_root=tmp_path,
        output_path=output_path,
        provider="dbt",
        dialect="duckdb",
        config_path="fitness_functions.yaml"
    )

    assert result_path == output_path
    assert output_path.exists()
    
    html_content = output_path.read_text(encoding="utf-8")
    assert "TFF Health & Documentation Dashboard" in html_content
    assert "const TFF_DATA =" in html_content
    assert "model_1" in html_content
    assert "model_2" in html_content


@patch("tff.core.cli._get_runner")
@patch("sqlmesh.core.context.Context")
@patch("tff.sqlmesh.runner.map_sqlmesh_context_models")
@patch("tff.core.docs.collect_stats")
@patch("tff.core.docs.save_log")
def test_generate_docs_dashboard_sqlmesh(
    mock_save_log,
    mock_collect_stats,
    mock_map_sqlmesh,
    mock_context,
    mock_get_runner,
    tmp_path: Path
):
    # Setup mock data for SQLMesh runner
    mock_runner = MagicMock()
    from tff.core.report import LintFinding
    mock_findings = [
        LintFinding(check="ban_select_star", severity="warning", model="model_1", path=None, message="banned select *"),
        LintFinding(check="layer_integrity", severity="error", model="model_2", path="models/model_2.sql", message="layer violation"),
        LintFinding(check="custom_exclusions", severity="error", message="project wide check violation")
    ]
    mock_runner.run_all_checks.return_value = (mock_findings, 2, ["sqlmesh"])
    mock_get_runner.return_value = mock_runner

    # Setup mock models mapping
    from tff.core.model import ModelRepresentation
    mock_model_1 = ModelRepresentation(
        name="model_1",
        path=str(tmp_path / "models/model_1.sql"),
        dialect="duckdb",
        materialized="table",
        depends_on=set()
    )
    mock_model_2 = ModelRepresentation(
        name="model_2",
        path=str(tmp_path / "models/model_2.sql"),
        dialect="duckdb",
        materialized="view",
        depends_on={"model_1"}
    )
    
    (tmp_path / "models").mkdir(parents=True, exist_ok=True)
    (tmp_path / "models/model_1.sql").touch()
    (tmp_path / "models/model_2.sql").touch()
    (tmp_path / "fitness_functions.yaml").touch()

    mock_map_sqlmesh.return_value = {
        "model_1": mock_model_1,
        "model_2": mock_model_2,
    }

    # Mock history as empty to cover fallback branch
    mock_collect_stats.return_value = []

    # Generate with default output_path (None)
    result_path = generate_docs_dashboard(
        project_root=tmp_path,
        output_path=None,
        provider="sqlmesh",
        config_path="fitness_functions.yaml"
    )

    expected_path = tmp_path / "tff_report.html"
    assert result_path == expected_path
    assert expected_path.exists()
    
    html_content = expected_path.read_text(encoding="utf-8")
    assert "model_1" in html_content
    assert "model_2" in html_content
    assert "warning" in html_content
    assert "error" in html_content


@patch("tff.core.cli._get_runner")
@patch("tff.dbt.manifest.load_dbt_models")
@patch("tff.core.docs.collect_stats")
@patch("tff.core.docs.save_log")
def test_generate_docs_dashboard_relative_output(
    mock_save_log,
    mock_collect_stats,
    mock_load_dbt_models,
    mock_get_runner,
    tmp_path: Path
):
    mock_runner = MagicMock()
    mock_runner.run_all_checks.return_value = ([], 0, [])
    mock_get_runner.return_value = mock_runner
    mock_load_dbt_models.return_value = {}
    mock_collect_stats.return_value = []
    
    (tmp_path / "fitness_functions.yaml").touch()

    # Relative output path
    relative_path = Path("reports/report.html")
    result_path = generate_docs_dashboard(
        project_root=tmp_path,
        output_path=relative_path,
        provider="dbt",
        config_path="fitness_functions.yaml"
    )

    assert result_path == tmp_path / "reports/report.html"
    assert result_path.exists()


@patch("tff.core.cli._detect_provider")
@patch("tff.core.docs.generate_docs_dashboard")
def test_cli_docs_command(
    mock_generate_docs,
    mock_detect_provider,
    tmp_path: Path
):
    mock_detect_provider.return_value = "dbt"
    mock_generate_docs.return_value = tmp_path / "tff_report.html"

    exit_code = main(["docs", "--project", str(tmp_path), "--output", str(tmp_path / "tff_report.html")])
    
    assert exit_code == 0
    mock_generate_docs.assert_called_once_with(
        project_root=tmp_path.resolve(),
        output_path=tmp_path / "tff_report.html",
        provider="dbt",
        dialect=None,
        config_path="fitness_functions.yaml"
    )


@patch("tff.core.cli._detect_provider")
@patch("tff.core.docs.generate_docs_dashboard")
def test_cli_docs_command_error(
    mock_generate_docs,
    mock_detect_provider,
    tmp_path: Path
):
    mock_detect_provider.return_value = "dbt"
    mock_generate_docs.side_effect = Exception("Failure")

    exit_code = main(["docs", "--project", str(tmp_path)])
    assert exit_code == 1


@patch("tff.core.cli._detect_provider")
def test_cli_docs_command_detect_error(
    mock_detect_provider,
    tmp_path: Path
):
    mock_detect_provider.side_effect = ValueError("Auto-detect failed")
    exit_code = main(["docs", "--project", str(tmp_path)])
    assert exit_code == 1


def test_help_docs_subcommand(capsys):
    assert main(["help", "docs"]) == 0
    captured = capsys.readouterr()
    assert "Generate HTML documentation and health dashboard" in captured.out
