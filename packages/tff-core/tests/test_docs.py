from conftest import _make_finding, _make_model
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tff.core.cli import main
from tff.core.docs import generate_docs_dashboard


@patch("tff.core.cli._get_adapter")
@patch("tff.core.docs.collect_stats")
@patch("tff.core.docs.save_log")
def test_generate_docs_dashboard_dbt(
    mock_save_log,
    mock_collect_stats,
    mock_get_adapter,
    tmp_path: Path
):
    # Setup mock adapter for dbt
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 2, ["rules"])
    mock_get_adapter.return_value = mock_adapter

    # Setup mock models
    mock_model_1 = _make_model(
        name="model_1",
        path=str(tmp_path / "models/model_1.sql"),
        dialect="duckdb",
        materialized="table",
        depends_on=set()
    )
    mock_model_2 = _make_model(
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

    mock_adapter.load_models.return_value = {
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
    assert "tff Health & Documentation Dashboard" in html_content
    assert "const TFF_DATA =" in html_content
    assert "model_1" in html_content
    assert "model_2" in html_content
    assert "This is an external source or seed not directly checked by tff rules." in html_content
    assert "checked by TFF rules" not in html_content


@patch("tff.core.cli._get_adapter")
@patch("tff.core.docs.collect_stats")
@patch("tff.core.docs.save_log")
def test_generate_docs_dashboard_sqlmesh(
    mock_save_log,
    mock_collect_stats,
    mock_get_adapter,
    tmp_path: Path
):
    # Setup mock adapter for SQLMesh
    mock_adapter = MagicMock()
    mock_findings = [
        _make_finding(check="ban_select_star", severity="warning", model="model_1", path=None, message="banned select *"),
        _make_finding(check="layer_integrity", severity="error", model="model_2", path="models/model_2.sql", message="layer violation"),
        _make_finding(check="custom_exclusions", severity="error", message="project wide check violation")
    ]
    mock_adapter.run_checks.return_value = (mock_findings, 2, ["sqlmesh"])
    mock_get_adapter.return_value = mock_adapter

    # Setup mock models mapping
    mock_model_1 = _make_model(
        name="model_1",
        path=str(tmp_path / "models/model_1.sql"),
        dialect="duckdb",
        materialized="table",
        depends_on=set()
    )
    mock_model_2 = _make_model(
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

    mock_adapter.load_models.return_value = {
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


@patch("tff.core.cli._get_adapter")
@patch("tff.core.docs.collect_stats")
@patch("tff.core.docs.save_log")
def test_generate_docs_dashboard_relative_output(
    mock_save_log,
    mock_collect_stats,
    mock_get_adapter,
    tmp_path: Path
):
    mock_adapter = MagicMock()
    mock_adapter.run_checks.return_value = ([], 0, [])
    mock_adapter.load_models.return_value = {}
    mock_get_adapter.return_value = mock_adapter
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
def test_cli_docs_command_no_log(
    mock_generate_docs,
    mock_detect_provider,
    tmp_path: Path
):
    mock_detect_provider.return_value = "dbt"
    mock_generate_docs.return_value = tmp_path / "tff_report.html"

    exit_code = main(["docs", "--project", str(tmp_path), "--output", str(tmp_path / "tff_report.html"), "--no-log"])
    
    assert exit_code == 0
    mock_generate_docs.assert_called_once_with(
        project_root=tmp_path.resolve(),
        output_path=tmp_path / "tff_report.html",
        provider="dbt",
        dialect=None,
        config_path="fitness_functions.yaml",
        no_log=True,
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
    assert "-p" in captured.out
    assert "--project" in captured.out


@patch("tff.core.cli._detect_provider")
@patch("tff.core.docs.generate_docs_dashboard")
def test_cli_docs_command_with_workers(mock_generate_docs, mock_detect_provider, tmp_path: Path):
    mock_detect_provider.return_value = "dbt"
    mock_generate_docs.return_value = tmp_path / "tff_report.html"

    exit_code = main(["docs", "--project", str(tmp_path), "--workers", "3"])
    assert exit_code == 0
    assert mock_generate_docs.call_args[1]["workers"] == 3


def test_generate_docs_dashboard_workers(tmp_path: Path):
    (tmp_path / "dbt_project.yml").touch()
    (tmp_path / "fitness_functions.yaml").touch()
    (tmp_path / "target").mkdir()
    (tmp_path / "target" / "manifest.json").write_text(
        '{"metadata": {"adapter_type": "duckdb"}, "nodes": {}, "sources": {}}',
        encoding="utf-8",
    )
    res = generate_docs_dashboard(tmp_path, workers=2, no_log=True)
    assert res.exists()


@patch("tff.core.cli._detect_provider")
@patch("tff.core.docs.generate_docs_dashboard")
def test_cli_docs_command_multi_project(
    mock_generate_docs,
    mock_detect_provider,
    tmp_path: Path,
):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    mock_detect_provider.return_value = "sqlmesh"
    mock_generate_docs.return_value = r1 / "tff_report.html"

    exit_code = main(["docs", "-p", str(r1), "-p", str(r2)])
    assert exit_code == 0
    mock_detect_provider.assert_called_once_with([r1.resolve(), r2.resolve()])
    mock_generate_docs.assert_called_once_with(
        project_root=[r1.resolve(), r2.resolve()],
        output_path=None,
        provider="sqlmesh",
        dialect=None,
        config_path="fitness_functions.yaml",
    )


def test_generate_docs_dashboard_multi_project(tmp_path: Path):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()
    (r1 / "dbt_project.yml").touch()
    (r2 / "dbt_project.yml").touch()
    (r1 / "fitness_functions.yaml").touch()
    (r1 / "target").mkdir()
    (r1 / "target" / "manifest.json").write_text(
        '{"metadata": {"adapter_type": "duckdb"}, "nodes": {}, "sources": {}}',
        encoding="utf-8",
    )
    (r2 / "target").mkdir()
    (r2 / "target" / "manifest.json").write_text(
        '{"metadata": {"adapter_type": "duckdb"}, "nodes": {}, "sources": {}}',
        encoding="utf-8",
    )
    res = generate_docs_dashboard([r1, r2], no_log=True)
    assert res.exists()
    assert res == r1 / "tff_report.html"


def test_generate_docs_dashboard_chunk_size(tmp_path: Path):
    from unittest.mock import patch
    from tff.dbt.adapter import DBTAdapter

    r = tmp_path / "repo"
    r.mkdir()
    (r / "dbt_project.yml").touch()
    (r / "fitness_functions.yaml").touch()
    (r / "target").mkdir()
    (r / "target" / "manifest.json").write_text(
        '{"metadata": {"adapter_type": "duckdb"}, "nodes": {}, "sources": {}}',
        encoding="utf-8",
    )

    with patch.object(DBTAdapter, "run_checks", autospec=True, side_effect=DBTAdapter.run_checks) as spy_run_checks:
        res = generate_docs_dashboard(r, chunk_size=8, no_log=True)
        assert res.exists()
        assert spy_run_checks.call_args.kwargs.get("chunk_size") == 8


@pytest.mark.parametrize(
    ("root_asset", "docs_asset"),
    [
        ("assets/favicon.svg", "docs/assets/favicon.svg"),
        ("assets/tff.svg", "docs/assets/tff.svg"),
    ],
)
def test_branding_assets_sync(root_asset: str, docs_asset: str) -> None:
    repo_root = Path(__file__).resolve().parents[3]
    root_file = repo_root / root_asset
    docs_file = repo_root / docs_asset
    assert root_file.exists(), f"{root_asset} does not exist"
    assert docs_file.exists(), f"{docs_asset} does not exist"
    assert root_file.read_text(encoding="utf-8") == docs_file.read_text(encoding="utf-8")


def test_readme_branding_asset_references() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    readme = (repo_root / "README.md").read_text(encoding="utf-8")
    assert "tff-white.svg" not in readme
    assert "docs/assets/tff.svg" not in readme


def test_dashboard_template_resource_loading() -> None:
    from tff.core.docs import HTML_TEMPLATE, _HTML_TEMPLATE, _load_dashboard_template

    loaded = _load_dashboard_template()
    assert loaded == HTML_TEMPLATE
    assert _HTML_TEMPLATE == HTML_TEMPLATE
    assert "<!-- INSERT_TFF_DATA_HERE -->" in loaded
    assert "tff Health & Documentation Dashboard" in loaded




