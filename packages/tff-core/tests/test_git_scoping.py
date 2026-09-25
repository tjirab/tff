"""Tests for git-scoping model evaluation (--staged and --since/--diff)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tff.core.config import FitnessFunctionsConfig
from tff.core.exceptions import TffGitError
from tff.core.git import (
    get_changed_files_since,
    get_git_root,
    get_staged_files,
    map_files_to_model_names,
)
from tff.core.model import ModelRepresentation
from tff.core.registry import registry
from tff.core.report import LintFinding
from tff.core.cli import main


def test_get_git_root_inside_repo() -> None:
    root = get_git_root(Path(__file__).parent)
    assert root is not None
    assert (root / ".git").exists()


def test_get_git_root_outside_repo(tmp_path: Path) -> None:
    root = get_git_root(tmp_path)
    assert root is None


def test_get_staged_files_mock() -> None:
    fake_root = Path("/fake/repo")
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "models/staging/stg_users.sql\nmodels/marts/dim_users.sql\n\n"

    with patch("subprocess.run", return_value=mock_res) as mock_run:
        files = get_staged_files(fake_root)
        mock_run.assert_called_once_with(
            ["git", "diff", "--cached", "--name-only"],
            cwd=str(fake_root),
            capture_output=True,
            text=True,
        )
        assert files == {
            "models/staging/stg_users.sql",
            "models/marts/dim_users.sql",
        }


def test_get_staged_files_error() -> None:
    fake_root = Path("/fake/repo")
    mock_res = MagicMock()
    mock_res.returncode = 1
    mock_res.stderr = "fatal: not a git repo"

    with patch("subprocess.run", return_value=mock_res):
        files = get_staged_files(fake_root)
        assert files == set()


def test_get_changed_files_since_success() -> None:
    fake_root = Path("/fake/repo")
    mock_res = MagicMock()
    mock_res.returncode = 0
    mock_res.stdout = "models/marts/dim_orders.sql\n"

    with patch("subprocess.run", return_value=mock_res):
        files = get_changed_files_since(fake_root, "origin/main")
        assert files == {"models/marts/dim_orders.sql"}


def test_get_changed_files_since_empty_ref() -> None:
    assert get_changed_files_since(Path("/fake/repo"), "   ") == set()


def test_get_changed_files_since_fallbacks() -> None:
    fake_root = Path("/fake/repo")
    fail_res = MagicMock(returncode=1)
    ok_res = MagicMock(returncode=0, stdout="models/marts/dim_direct.sql\n")

    # 1. 3-dot fails, 2-dot direct succeeds
    with patch("subprocess.run", side_effect=[fail_res, ok_res]):
        files = get_changed_files_since(fake_root, "feature-branch")
        assert files == {"models/marts/dim_direct.sql"}

    # 2. 3-dot fails, 2-dot fails, origin/ branch succeeds
    with patch("subprocess.run", side_effect=[fail_res, fail_res, ok_res]):
        files = get_changed_files_since(fake_root, "feature-branch")
        assert files == {"models/marts/dim_direct.sql"}


def test_get_changed_files_since_invalid_ref() -> None:
    fake_root = Path("/fake/repo")
    diff_fail = MagicMock(returncode=1)

    with patch("subprocess.run", return_value=diff_fail):
        with pytest.raises(TffGitError, match="Unknown or invalid git reference: 'nonexistent-branch'"):
            get_changed_files_since(fake_root, "nonexistent-branch")


def test_map_files_to_model_names() -> None:
    models = {
        "dim_users": ModelRepresentation(
            name="dim_users",
            path="models/marts/dim_users.sql",
            dialect="duckdb",
        ),
        "stg_orders": ModelRepresentation(
            name="stg_orders",
            path="models/staging/stg_orders.sql",
            dialect="duckdb",
        ),
        "fct_revenue": ModelRepresentation(
            name="fct_revenue",
            path="models/marts/finance/fct_revenue.sql",
            dialect="duckdb",
        ),
    }

    project_root = Path("/repo/dbt_project")
    repo_root = Path("/repo")

    # Empty inputs
    assert map_files_to_model_names({}, {"file.sql"}, project_root, repo_root) == set()
    assert map_files_to_model_names(models, set(), project_root, repo_root) == set()

    # 1. Exact match with project prefix
    files = {"dbt_project/models/marts/dim_users.sql", "README.md"}
    matched = map_files_to_model_names(models, files, project_root, repo_root)
    assert matched == {"dim_users"}

    # 2. File stem match
    files = {"stg_orders.sql"}
    matched = map_files_to_model_names(models, files, project_root, repo_root)
    assert matched == {"stg_orders"}

    # 3. Path suffix match
    files = {"models/marts/finance/fct_revenue.sql"}
    matched = map_files_to_model_names(models, files, project_root, repo_root)
    assert matched == {"fct_revenue"}

    # 4. Unrelated files only
    files = {"docs/overview.md", ".pre-commit-hooks.yaml"}
    matched = map_files_to_model_names(models, files, project_root, repo_root)
    assert matched == set()

    # 5. Project outside repo root (triggers relative_to exception)
    matched_diff_root = map_files_to_model_names(models, {"stg_orders.sql"}, Path("/other/dir"), Path("/repo"))
    assert matched_diff_root == {"stg_orders"}


def test_check_definition_run_scoped_models() -> None:
    rule_check = registry.get("ban_select_star")
    assert rule_check is not None
    assert rule_check.scope == "model"

    config = FitnessFunctionsConfig()
    models = {
        "model_clean": ModelRepresentation(
            name="model_clean",
            path="clean.sql",
            dialect="duckdb",
            query="SELECT id FROM tbl",
        ),
        "model_bad": ModelRepresentation(
            name="model_bad",
            path="bad.sql",
            dialect="duckdb",
            query="SELECT * FROM tbl",
        ),
    }

    findings_clean = rule_check.run(models, config, scoped_models={"model_clean"})
    assert len(findings_clean) == 0

    findings_bad = rule_check.run(models, config, scoped_models={"model_bad"})
    assert len(findings_bad) == 1
    assert findings_bad[0].model == "model_bad"


def test_check_definition_run_dag_check_scoped_models() -> None:
    dag_check = registry.get("layer_integrity")
    assert dag_check is not None
    assert dag_check.scope == "dag"

    config = FitnessFunctionsConfig()
    config.layers.order = ["staging", "core", "marts"]
    config.checks.layer_integrity.enabled = True

    models = {
        "stg_customers": ModelRepresentation(
            name="stg_customers",
            path="models/staging/stg_customers.sql",
            dialect="duckdb",
            depends_on={"dim_orders"},
        ),
        "dim_orders": ModelRepresentation(
            name="dim_orders",
            path="models/marts/dim_orders.sql",
            dialect="duckdb",
            depends_on=set(),
        ),
        "stg_payments": ModelRepresentation(
            name="stg_payments",
            path="models/staging/stg_payments.sql",
            dialect="duckdb",
            depends_on={"dim_orders"},
        ),
    }

    scoped_findings = dag_check.run(models, config, scoped_models={"stg_customers"})
    assert len(scoped_findings) == 1
    assert scoped_findings[0].model == "stg_customers"


def test_cli_lint_staged_no_modified_models(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: test_proj\nversion: '1.0.0'\n", encoding="utf-8")
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / "dim_users.sql").write_text("SELECT * FROM raw", encoding="utf-8")

    with patch("tff.core.git.get_git_root", return_value=tmp_path):
        with patch("tff.core.git.get_staged_files", return_value=set()):
            with patch("sys.stdout"):
                ret = main(["check", "-p", str(tmp_path), "--staged"])
                assert ret == 0


def test_cli_lint_staged_with_violation(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: test_proj\nversion: '1.0.0'\n", encoding="utf-8")
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    manifest_json = {
        "metadata": {"adapter_type": "duckdb"},
        "nodes": {
            "model.test_proj.dim_users": {
                "resource_type": "model",
                "name": "dim_users",
                "original_file_path": "models/marts/dim_users.sql",
                "raw_code": "SELECT * FROM raw",
                "columns": {},
                "depends_on": {"nodes": []},
            },
            "model.test_proj.dim_clean": {
                "resource_type": "model",
                "name": "dim_clean",
                "original_file_path": "models/marts/dim_clean.sql",
                "raw_code": "SELECT id FROM raw",
                "columns": {},
                "depends_on": {"nodes": []},
            }
        }
    }
    import json
    (target_dir / "manifest.json").write_text(json.dumps(manifest_json), encoding="utf-8")
    marts_dir = tmp_path / "models" / "marts"
    marts_dir.mkdir(parents=True)
    (marts_dir / "dim_users.sql").write_text("SELECT * FROM raw", encoding="utf-8")
    (marts_dir / "dim_clean.sql").write_text("SELECT id FROM raw", encoding="utf-8")

    with patch("tff.core.git.get_git_root", return_value=tmp_path):
        # 1. Stage only the clean model -> passes
        with patch("tff.core.git.get_staged_files", return_value={"models/marts/dim_clean.sql"}):
            with patch("sys.stdout"):
                ret_clean = main(["check", "-p", str(tmp_path), "--staged", "--checks", "ban_select_star"])
                assert ret_clean == 0

        # 2. Stage the violating model -> fails with 1
        with patch("tff.core.git.get_staged_files", return_value={"models/marts/dim_users.sql"}):
            with patch("sys.stdout"):
                ret_bad = main(["check", "-p", str(tmp_path), "--staged", "--checks", "ban_select_star"])
                assert ret_bad == 1


def test_cli_lint_since_ref(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: test_proj\nversion: '1.0.0'\n", encoding="utf-8")
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    manifest_json = {
        "metadata": {"adapter_type": "duckdb"},
        "nodes": {
            "model.test_proj.dim_clean": {
                "resource_type": "model",
                "name": "dim_clean",
                "original_file_path": "models/marts/dim_clean.sql",
                "raw_code": "SELECT id FROM raw",
                "columns": {},
                "depends_on": {"nodes": []},
            }
        }
    }
    import json
    (target_dir / "manifest.json").write_text(json.dumps(manifest_json), encoding="utf-8")
    marts_dir = tmp_path / "models" / "marts"
    marts_dir.mkdir(parents=True)
    (marts_dir / "dim_clean.sql").write_text("SELECT id FROM raw", encoding="utf-8")

    with patch("tff.core.git.get_git_root", return_value=tmp_path):
        with patch("tff.core.git.get_changed_files_since", return_value={"models/marts/dim_clean.sql"}):
            with patch("sys.stdout"):
                ret = main(["check", "-p", str(tmp_path), "--since", "HEAD~1", "--checks", "ban_select_star"])
                assert ret == 0


def test_cli_health_staged(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: test_proj\nversion: '1.0.0'\n", encoding="utf-8")
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    manifest_json = {
        "metadata": {"adapter_type": "duckdb"},
        "nodes": {
            "model.test_proj.dim_clean": {
                "resource_type": "model",
                "name": "dim_clean",
                "original_file_path": "models/marts/dim_clean.sql",
                "raw_code": "SELECT id FROM raw",
                "columns": {},
                "depends_on": {"nodes": []},
            }
        }
    }
    import json
    (target_dir / "manifest.json").write_text(json.dumps(manifest_json), encoding="utf-8")
    marts_dir = tmp_path / "models" / "marts"
    marts_dir.mkdir(parents=True)
    (marts_dir / "dim_clean.sql").write_text("SELECT id FROM raw", encoding="utf-8")

    with patch("tff.core.git.get_git_root", return_value=tmp_path):
        with patch("tff.core.git.get_staged_files", return_value={"models/marts/dim_clean.sql"}):
            with patch("sys.stdout"):
                ret = main(["health", "-p", str(tmp_path), "--staged"])
                assert ret == 0


def test_cli_git_scoping_not_in_repo(tmp_path: Path) -> None:
    (tmp_path / "dbt_project.yml").write_text("name: test_proj\nversion: '1.0.0'\n", encoding="utf-8")
    with patch("tff.core.git.get_git_root", return_value=None):
        ret = main(["check", "-p", str(tmp_path), "--staged"])
        assert ret == 1


def test_dataform_runner_scoped_models(tmp_path: Path) -> None:
    from tff.dataform.runner import run_all_checks
    from tff.core.report import LintFinding

    cfg = FitnessFunctionsConfig()
    models = {
        "model_a": ModelRepresentation(
            name="model_a",
            path="definitions/model_a.sqlx",
            dialect="bigquery",
        ),
        "model_b": ModelRepresentation(
            name="model_b",
            path="definitions/model_b.sqlx",
            dialect="bigquery",
        ),
    }

    mock_finding = LintFinding(
        check="layer_integrity",
        severity="error",
        model="model_a",
        message="Violates layer conventions",
    )

    with patch("tff.core.registry.registry.run_checks", return_value=([mock_finding], ["layer_integrity"])):
        findings, count, sel = run_all_checks(
            project_root=tmp_path,
            config=cfg,
            models=models,
            scoped_models={"model_a"},
        )
        assert count == 1
        assert len(findings) == 1


def test_sqlmesh_runner_scoped_models(tmp_path: Path) -> None:
    from tff.sqlmesh.runner import run_all_checks, collect_sqlmesh_findings

    cfg = FitnessFunctionsConfig()
    models = {
        "model_a": ModelRepresentation(
            name="model_a",
            path="models/model_a.sql",
            dialect="duckdb",
        ),
        "model_b": ModelRepresentation(
            name="model_b",
            path="models/model_b.sql",
            dialect="duckdb",
        ),
    }

    # 1. collect_sqlmesh_findings with scoped_models filters models
    mock_ctx = MagicMock()
    mock_m1 = MagicMock()
    mock_m1.name = "model_a"
    mock_m1.kind.is_symbolic = False
    mock_m1.project = "p"
    mock_m2 = MagicMock()
    mock_m2.name = "model_b"
    mock_m2.kind.is_symbolic = False
    mock_m2.project = "p"
    mock_ctx.models = {"model_a": mock_m1, "model_b": mock_m2}

    mock_linter = MagicMock()
    mock_linter.enabled = True
    mock_linter.lint_model.return_value = (None, [])
    mock_ctx._linters = {"p": mock_linter}

    collect_sqlmesh_findings(mock_ctx, config=cfg, scoped_models={"model_a"})
    mock_linter.lint_model.assert_called_once()
    assert mock_linter.lint_model.call_args[0][0].name == "model_a"

    # 2. run_all_checks with checks=None and scoped_models
    finding_a = LintFinding(check="layer_integrity", severity="error", model="model_a", message="err")
    finding_b = LintFinding(check="layer_integrity", severity="error", model="model_b", message="err")
    with patch("tff.sqlmesh.runner.CHECK_COLLECTORS", {"layer_integrity": lambda m, c: [finding_a, finding_b]}):
        findings, count, _ = run_all_checks(
            project_root=tmp_path,
            config=cfg,
            models=models,
            checks=None,
            scoped_models={"model_a"},
        )
        assert count == 1
        assert len(findings) == 1
        assert findings[0].model == "model_a"

    # 3. run_all_checks with checks=["layer_integrity"] and scoped_models
    with patch("tff.sqlmesh.runner.registry.get") as mock_get:
        mock_cdef = MagicMock()
        mock_cdef.scope = "dag"
        mock_cdef.get_collector_fn.return_value = lambda m, c: [finding_a, finding_b]
        mock_get.return_value = mock_cdef

        findings, count, _ = run_all_checks(
            project_root=tmp_path,
            config=cfg,
            models=models,
            checks=["layer_integrity"],
            scoped_models={"model_a"},
        )
        assert count == 1
        assert len(findings) == 1
        assert findings[0].model == "model_a"
