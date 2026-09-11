"""Tests for TFF GitHub Action runner, baseline diff, PR commenting, and action manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

import pytest
import yaml

from tff.core.action import (
    PR_COMMENT_MARKER,
    compare_findings,
    detect_pr_context,
    evaluate_pass_fail,
    evaluate_project,
    execute_action,
    fetch_base_scores,
    generate_pr_comment_markdown,
    get_finding_fingerprint,
    get_modified_files,
    is_finding_in_files,
    parse_bool,
    post_or_update_pr_comment,
    write_github_output,
    write_github_step_summary,
)
from tff.core.cli import main
from tff.core.report import LintFinding

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MINIMAL_DBT = _REPO_ROOT / "examples" / "minimal-dbt-project"


def test_action_yml_exists_and_matches_composite_manifest() -> None:
    root_manifest = _REPO_ROOT / "action.yml"
    sub_manifest = _REPO_ROOT / ".github" / "actions" / "tff" / "action.yml"

    assert root_manifest.is_file(), "action.yml must exist at repository root for Marketplace publication"
    assert sub_manifest.is_file(), ".github/actions/tff/action.yml must exist"

    root_content = yaml.safe_load(root_manifest.read_text(encoding="utf-8"))
    sub_content = yaml.safe_load(sub_manifest.read_text(encoding="utf-8"))

    assert root_content == sub_content, "action.yml and .github/actions/tff/action.yml must match"

    # Verify required Marketplace metadata
    assert root_content["name"] == "TFF - Transformation Fitness Functions"
    assert "Architectural linter and health score engine" in root_content["description"]
    assert root_content["author"] == "Bart Schuijt"
    assert root_content["branding"]["icon"] in ("check-circle", "shield", "activity")
    assert root_content["branding"]["color"] in ("blue", "purple", "green")

    # Verify inputs
    inputs = root_content["inputs"]
    assert "project" in inputs
    assert inputs["project"]["default"] == "."
    assert "provider" in inputs
    assert inputs["provider"]["default"] == "auto"
    assert "fail-under" in inputs
    assert inputs["fail-under"]["default"] == "0.0"
    assert "fail-level" in inputs
    assert inputs["fail-level"]["default"] == "error"
    assert "comment-pr" in inputs
    assert inputs["comment-pr"]["default"] == "false"
    assert "github-token" in inputs
    assert "config" in inputs
    assert "checks" in inputs
    assert "python-version" in inputs
    assert "version" in inputs
    assert "annotations" in inputs
    assert "diff-against-base" in inputs

    # Verify outputs
    outputs = root_content["outputs"]
    assert "health-score" in outputs
    assert "violations-count" in outputs
    assert "errors-count" in outputs
    assert "warnings-count" in outputs
    assert "passed" in outputs
    assert "comment-id" in outputs

    # Verify runs using composite
    assert root_content["runs"]["using"] == "composite"
    assert len(root_content["runs"]["steps"]) >= 3


def test_parse_bool() -> None:
    assert parse_bool(True) is True
    assert parse_bool(False) is False
    assert parse_bool("true") is True
    assert parse_bool("True") is True
    assert parse_bool("1") is True
    assert parse_bool("yes") is True
    assert parse_bool("on") is True
    assert parse_bool("false") is False
    assert parse_bool("0") is False
    assert parse_bool("no") is False
    assert parse_bool(1) is True
    assert parse_bool(0) is False


def test_finding_fingerprint_and_comparison() -> None:
    finding_obj = LintFinding(
        check="banselectstar",
        severity="error",
        message="SELECT * is banned",
        model="stg_orders",
        path=Path("models/staging/stg_orders.sql"),
        line=10,
    )
    finding_dict = {
        "check": "banselectstar",
        "severity": "error",
        "message": "SELECT * is banned",
        "model": "stg_orders",
        "path": "models/staging/stg_orders.sql",
    }

    fp1 = get_finding_fingerprint(finding_obj)
    fp2 = get_finding_fingerprint(finding_dict)
    assert fp1 == fp2 == ("banselectstar", "stg_orders", "SELECT * is banned")

    base_findings = [finding_obj]
    new_finding = {
        "check": "columnnames",
        "severity": "warning",
        "message": "Column name invalid",
        "model": "dim_customers",
        "path": "models/dim_customers.sql",
    }
    current_findings = [finding_dict, new_finding]

    new_viols, resolved_viols = compare_findings(current_findings, base_findings)
    assert len(new_viols) == 1
    assert new_viols[0]["check"] == "columnnames"
    assert len(resolved_viols) == 0

    # Test resolved
    new_viols2, resolved_viols2 = compare_findings([], base_findings)
    assert len(new_viols2) == 0
    assert len(resolved_viols2) == 1
    assert resolved_viols2[0]["check"] == "banselectstar"


def test_evaluate_project_minimal_dbt() -> None:
    data = evaluate_project(_MINIMAL_DBT, provider="auto")
    assert data["provider"] == "dbt"
    assert data["models_checked"] == 4
    assert data["overall_score"] > 0.0
    assert "findings" in data
    assert data["errors_count"] >= 0
    assert data["warnings_count"] >= 0
    assert "Connascence of Name (CoN)" in data["category_scores"]


def test_evaluate_pass_fail() -> None:
    data_pass = {
        "overall_score": 90.0,
        "errors_count": 0,
        "warnings_count": 0,
    }
    assert evaluate_pass_fail(data_pass, fail_under=80.0, fail_level="error") is True
    assert evaluate_pass_fail(data_pass, fail_under=95.0, fail_level="error") is False

    data_warnings = {
        "overall_score": 85.0,
        "errors_count": 0,
        "warnings_count": 2,
    }
    assert evaluate_pass_fail(data_warnings, fail_under=80.0, fail_level="error") is True
    assert evaluate_pass_fail(data_warnings, fail_under=80.0, fail_level="warning") is False

    data_errors = {
        "overall_score": 85.0,
        "errors_count": 1,
        "warnings_count": 0,
    }
    assert evaluate_pass_fail(data_errors, fail_under=80.0, fail_level="error") is False
    assert evaluate_pass_fail(data_errors, fail_under=0.0, fail_level="error") is False


def test_generate_pr_comment_markdown_clean_run() -> None:
    clean_data = {
        "overall_score": 100.0,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
        "category_scores": {"Connascence of Name (CoN)": 100.0},
    }
    md = generate_pr_comment_markdown(clean_data, base_data=None, fail_under=80.0, fail_level="error")
    assert PR_COMMENT_MARKER in md
    assert "100.0%" in md
    assert "PASSED" in md
    assert "All architectural fitness functions and linter checks passed without any violations!" in md
    assert "### 📊 Health Score by Category" in md


def test_generate_pr_comment_markdown_with_diff_and_violations() -> None:
    current_data = {
        "overall_score": 92.0,
        "findings": [
            {
                "check": "banselectstar",
                "severity": "error",
                "message": "SELECT * not allowed",
                "model": "stg_orders",
                "path": "models/stg_orders.sql",
            },
            {
                "check": "duplicate_ctes",
                "severity": "warning",
                "message": "Duplicate CTE found",
                "model": "int_orders",
                "path": "models/int_orders.sql",
            },
        ],
        "errors_count": 1,
        "warnings_count": 1,
        "category_scores": {"Connascence of Name (CoN)": 90.0, "Connascence of Algorithm (CoA)": 94.0},
    }
    base_data = {
        "overall_score": 88.0,
        "findings": [
            {
                "check": "old_check",
                "severity": "warning",
                "message": "Old issue resolved",
                "model": "stg_customers",
                "path": "models/stg_customers.sql",
            }
        ],
        "errors_count": 0,
        "warnings_count": 1,
    }

    md = generate_pr_comment_markdown(current_data, base_data=base_data, fail_under=80.0, fail_level="error", base_ref="main")
    assert PR_COMMENT_MARKER in md
    assert "+4.0% vs main" in md
    assert "Changes vs `main`" in md
    assert "Resolved Violations" in md
    assert "New Violations" in md
    assert "New Violations Introduced" in md
    assert "All Violations" not in md  # Violations Detail
    assert "Violations Detail (2)" in md
    assert "banselectstar" in md


def test_generate_pr_comment_markdown_negative_diff_and_truncation() -> None:
    current_data = {
        "overall_score": 75.0,
        "findings": [
            {
                "check": f"check_{i}",
                "severity": "error",
                "message": f"Violation message {i}",
                "model": f"model_{i}",
                "path": f"models/model_{i}.sql",
            }
            for i in range(55)
        ],
        "errors_count": 55,
        "warnings_count": 0,
        "category_scores": {},
    }
    base_data = {
        "overall_score": 80.0,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
    }
    md = generate_pr_comment_markdown(current_data, base_data=base_data, fail_under=80.0, fail_level="error", base_ref="main")
    assert "-5.0% vs main" in md
    assert "FAILED" in md
    assert "more violations truncated" in md


def test_generate_pr_comment_markdown_zero_diff() -> None:
    current_data = {
        "overall_score": 85.0,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
        "category_scores": {},
    }
    base_data = {
        "overall_score": 85.02,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
    }
    md = generate_pr_comment_markdown(current_data, base_data=base_data, fail_under=80.0, fail_level="error", base_ref="main")
    assert "0.0% vs main" in md


def test_post_or_update_pr_comment_no_token() -> None:
    res = post_or_update_pr_comment("", "owner/repo", 123, "body")
    assert res is None


def test_post_or_update_pr_comment_create_new() -> None:
    mock_list_resp = MagicMock()
    mock_list_resp.read.return_value = json.dumps([
        {"id": 101, "body": "some other comment"},
    ]).encode("utf-8")
    mock_list_resp.__enter__.return_value = mock_list_resp

    mock_post_resp = MagicMock()
    mock_post_resp.read.return_value = json.dumps({"id": 999}).encode("utf-8")
    mock_post_resp.__enter__.return_value = mock_post_resp

    with patch("urllib.request.urlopen", side_effect=[mock_list_resp, mock_post_resp]) as mock_open:
        cid = post_or_update_pr_comment("fake_token", "owner/repo", 42, "hello world")
        assert cid == 999
        assert mock_open.call_count == 2
        req2 = mock_open.call_args_list[1][0][0]
        assert req2.method == "POST"
        assert "42/comments" in req2.full_url


def test_post_or_update_pr_comment_update_existing() -> None:
    mock_list_resp = MagicMock()
    mock_list_resp.read.return_value = json.dumps([
        {"id": 202, "body": f"old report\n{PR_COMMENT_MARKER}"},
    ]).encode("utf-8")
    mock_list_resp.__enter__.return_value = mock_list_resp

    mock_patch_resp = MagicMock()
    mock_patch_resp.read.return_value = json.dumps({"id": 202}).encode("utf-8")
    mock_patch_resp.__enter__.return_value = mock_patch_resp

    with patch("urllib.request.urlopen", side_effect=[mock_list_resp, mock_patch_resp]) as mock_open:
        cid = post_or_update_pr_comment("fake_token", "owner/repo", 42, "updated report")
        assert cid == 202
        assert mock_open.call_count == 2
        req2 = mock_open.call_args_list[1][0][0]
        assert req2.method == "PATCH"
        assert "comments/202" in req2.full_url


def test_post_or_update_pr_comment_http_errors() -> None:
    err = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
    with patch("urllib.request.urlopen", side_effect=err):
        cid = post_or_update_pr_comment("fake_token", "owner/repo", 42, "body")
        assert cid is None

    # Error during POST
    mock_list_resp = MagicMock()
    mock_list_resp.read.return_value = b"[]"
    mock_list_resp.__enter__.return_value = mock_list_resp
    with patch("urllib.request.urlopen", side_effect=[mock_list_resp, err]):
        cid = post_or_update_pr_comment("fake_token", "owner/repo", 42, "body")
        assert cid is None

    # General Exception
    with patch("urllib.request.urlopen", side_effect=Exception("network error")):
        cid = post_or_update_pr_comment("fake_token", "owner/repo", 42, "body")
        assert cid is None


def test_detect_pr_context(tmp_path: Path) -> None:
    # 1. From event file
    event_file = tmp_path / "event.json"
    event_file.write_text(
        json.dumps({
            "pull_request": {"number": 88},
            "repository": {"full_name": "tjirab/tff"},
        }),
        encoding="utf-8",
    )
    with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_file)}, clear=True):
        repo, pr = detect_pr_context()
        assert repo == "tjirab/tff"
        assert pr == 88

    # 2. From GITHUB_REF
    with patch.dict(
        os.environ,
        {"GITHUB_REF": "refs/pull/99/merge", "GITHUB_REPOSITORY": "tjirab/tff"},
        clear=True,
    ):
        repo, pr = detect_pr_context()
        assert repo == "tjirab/tff"
        assert pr == 99

    # 3. Neither
    with patch.dict(os.environ, {}, clear=True):
        repo, pr = detect_pr_context()
        assert repo is None
        assert pr is None


def test_github_env_helpers(tmp_path: Path) -> None:
    out_file = tmp_path / "output.txt"
    summary_file = tmp_path / "summary.md"

    with patch.dict(
        os.environ,
        {"GITHUB_OUTPUT": str(out_file), "GITHUB_STEP_SUMMARY": str(summary_file)},
    ):
        write_github_output("score", "95.5")
        write_github_step_summary("## Summary Report")

    assert "score=95.5" in out_file.read_text(encoding="utf-8")
    assert "## Summary Report" in summary_file.read_text(encoding="utf-8")


def test_fetch_base_scores_failures(tmp_path: Path) -> None:
    # Directory outside git repo
    scores = fetch_base_scores(tmp_path, "main")
    assert scores is None

    # Mock git rev-parse success but git worktree failure
    with patch("subprocess.run") as mock_run:
        mock_res1 = MagicMock(stdout=str(_REPO_ROOT) + "\n", returncode=0)
        mock_res_fail = MagicMock(stderr="fatal: not a valid object", returncode=1)
        mock_run.side_effect = [mock_res1, MagicMock(returncode=0), mock_res_fail, mock_res_fail, MagicMock(returncode=0)]
        scores = fetch_base_scores(_MINIMAL_DBT, "nonexistent-branch")
        assert scores is None


def test_execute_action_cli_json_and_annotations(tmp_path: Path) -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks="layer_integrity",
        fail_under=80.0,
        fail_level="error",
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=True,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=True,
    )

    out_file = tmp_path / "output.txt"
    summary_file = tmp_path / "summary.md"
    with patch.dict(
        os.environ,
        {"GITHUB_OUTPUT": str(out_file), "GITHUB_STEP_SUMMARY": str(summary_file)},
    ):
        code = execute_action(args)
        assert code == 0
        assert "passed=true" in out_file.read_text(encoding="utf-8")
        assert "## 🎯 Transformation Fitness Functions Report" in summary_file.read_text(encoding="utf-8")


def test_execute_action_cli_with_annotations_and_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,  # 7 findings exist
        fail_under=0.0,
        fail_level="error",
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=True,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )
    with patch("tff.core.action.render_health_report"):
        code = execute_action(args)
        assert code == 1
        captured = capsys.readouterr()
        assert "::error" in captured.out



def test_execute_action_cli_fail_and_pr_comment(tmp_path: Path) -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,
        fail_under=95.0,  # will fail (minimal-dbt is ~91.7)
        fail_level="error",
        comment_pr="true",
        github_token="fake_token",
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=50,
        repo="tjirab/tff",
        dialect=None,
        manifest=None,
        json=False,
    )

    out_file = tmp_path / "output.txt"
    with patch("tff.core.action.post_or_update_pr_comment", return_value=777) as mock_post:
        with patch.dict(os.environ, {"GITHUB_OUTPUT": str(out_file)}):
            code = execute_action(args)
            assert code == 1
            mock_post.assert_called_once()
            assert "comment-id=777" in out_file.read_text(encoding="utf-8")
            assert "passed=false" in out_file.read_text(encoding="utf-8")


def test_execute_action_evaluation_error() -> None:
    args = argparse.Namespace(
        project=Path("/nonexistent/directory/12345"),
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,
        fail_under=0.0,
        fail_level="error",
        comment_pr="false",
    )
    code = execute_action(args)
    assert code == 1


def test_cli_action_subcommand(capsys: pytest.CaptureFixture[str]) -> None:
    # Test help
    assert main(["help", "action"]) == 0
    captured = capsys.readouterr()
    assert "Run TFF checks" in captured.out

    # Test passing execution
    assert main([
        "action",
        "--project", str(_MINIMAL_DBT),
        "--checks", "layer_integrity",
        "--no-annotations",
        "--fail-under", "0",
        "--fail-level", "error",
    ]) == 0

    # Test failing execution
    assert main([
        "action",
        "--project", str(_MINIMAL_DBT),
        "--no-annotations",
        "--fail-under", "99.0",
    ]) == 1


def test_fetch_base_scores_success(tmp_path: Path) -> None:
    # Setup dummy project inside temp dir
    proj_dir = tmp_path / "repo" / "my_project"
    proj_dir.mkdir(parents=True)

    dummy_scores = {"overall_score": 90.0, "findings": []}
    with patch("subprocess.run") as mock_run, patch(
        "tff.core.action.evaluate_project", return_value=dummy_scores
    ) as mock_eval:
        mock_run.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout=str(tmp_path / "repo") + "\n", returncode=0)
            if "rev-parse" in cmd
            else MagicMock(returncode=0)
        )
        with patch("tempfile.mkdtemp") as mock_mkdtemp:
            worktree_dir = tmp_path / "worktree"
            (worktree_dir / "my_project").mkdir(parents=True)
            mock_mkdtemp.return_value = str(worktree_dir)

            res = fetch_base_scores(proj_dir, "main")
            assert res == dummy_scores
            mock_eval.assert_called_once()


def test_fetch_base_scores_base_project_dir_not_found(tmp_path: Path) -> None:
    proj_dir = tmp_path / "repo" / "missing_subproject"
    proj_dir.mkdir(parents=True)

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout=str(tmp_path / "repo") + "\n", returncode=0)
            if "rev-parse" in cmd
            else MagicMock(returncode=0)
        )
        with patch("tempfile.mkdtemp") as mock_mkdtemp:
            worktree_dir = tmp_path / "worktree2"
            worktree_dir.mkdir(parents=True)
            mock_mkdtemp.return_value = str(worktree_dir)

            res = fetch_base_scores(proj_dir, "main")
            assert res is None


def test_fetch_base_scores_general_exception(tmp_path: Path) -> None:
    proj_dir = tmp_path / "repo"
    proj_dir.mkdir(parents=True)

    def _side_effect(cmd, **kwargs):
        if "rev-parse" in cmd:
            return MagicMock(stdout=str(proj_dir) + "\n", returncode=0)
        elif "worktree" in cmd and "remove" in cmd:
            return MagicMock(returncode=0)
        raise RuntimeError("git crash")

    with patch("subprocess.run", side_effect=_side_effect):
        res = fetch_base_scores(proj_dir, "main")
        assert res is None


def test_post_or_update_pr_comment_patch_exception() -> None:
    mock_list_resp = MagicMock()
    mock_list_resp.read.return_value = json.dumps([
        {"id": 303, "body": f"old report\n{PR_COMMENT_MARKER}"},
    ]).encode("utf-8")
    mock_list_resp.__enter__.return_value = mock_list_resp

    with patch("urllib.request.urlopen", side_effect=[mock_list_resp, RuntimeError("network drop")]):
        cid = post_or_update_pr_comment("fake_token", "owner/repo", 42, "updated report")
        assert cid is None


def test_detect_pr_context_corrupted_json(tmp_path: Path) -> None:
    corrupt_file = tmp_path / "bad_event.json"
    corrupt_file.write_text("{ not valid json", encoding="utf-8")
    with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(corrupt_file)}, clear=True):
        repo, pr = detect_pr_context()
        assert repo is None
        assert pr is None


def test_detect_pr_context_invalid_ref() -> None:
    with patch.dict(os.environ, {"GITHUB_REF": "refs/pull/notanumber/merge"}, clear=True):
        repo, pr = detect_pr_context()
        assert repo is None
        assert pr is None


def test_github_env_helpers_exceptions() -> None:
    # Invalid paths triggering IOError
    with patch.dict(os.environ, {"GITHUB_OUTPUT": "/nonexistent_dir/impossible/out.txt"}):
        write_github_output("key", "value")

    with patch.dict(os.environ, {"GITHUB_STEP_SUMMARY": "/nonexistent_dir/impossible/summary.md"}):
        write_github_step_summary("summary content")


def test_execute_action_cli_with_base_diff_and_auto_pr(tmp_path: Path) -> None:
    event_file = tmp_path / "event.json"
    event_file.write_text(
        json.dumps({
            "pull_request": {"number": 12},
            "repository": {"full_name": "tjirab/tff"},
        }),
        encoding="utf-8",
    )

    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks="layer_integrity",
        fail_under=80.0,
        fail_level="error",
        comment_pr="true",
        github_token="fake_token",
        base_ref="main",
        diff_against_base=True,
        annotations=True,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )

    dummy_base_data = {
        "overall_score": 95.0,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
    }

    with patch("tff.core.action.fetch_base_scores", return_value=dummy_base_data), patch(
        "tff.core.action.post_or_update_pr_comment", return_value=888
    ) as mock_post, patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_file)}):
        code = execute_action(args)
        assert code == 0
        mock_post.assert_called_once()
        assert mock_post.call_args[1]["repo"] == "tjirab/tff"
        assert mock_post.call_args[1]["pr_number"] == 12


def test_execute_action_comment_pr_no_context(capsys: pytest.CaptureFixture[str]) -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks="layer_integrity",
        fail_under=80.0,
        fail_level="error",
        comment_pr="true",
        github_token="fake_token",
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )

    with patch.dict(os.environ, {}, clear=True):
        code = execute_action(args)
        assert code == 0
        captured = capsys.readouterr()
        assert "Notice: comment-pr is enabled, but could not detect pull request context" in captured.err


def test_action_manifest_has_only_changed() -> None:
    root_manifest = _REPO_ROOT / "action.yml"
    root_content = yaml.safe_load(root_manifest.read_text(encoding="utf-8"))
    assert "only-changed" in root_content["inputs"]
    assert root_content["inputs"]["only-changed"]["default"] == "false"


def test_get_modified_files(tmp_path: Path) -> None:
    # 1. Success on origin/{base_ref}...HEAD
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="models/marts/dim_customers.sql\nmodels/staging/stg_orders.sql\n")
        files = get_modified_files(tmp_path, base_ref="main")
        assert files == {"models/marts/dim_customers.sql", "models/staging/stg_orders.sql"}

    # 2. Fallback to {base_ref}...HEAD
    with patch("subprocess.run") as mock_run:
        mock_fail = MagicMock(returncode=1)
        mock_ok = MagicMock(returncode=0, stdout="models/staging/stg_orders.sql\n")
        mock_run.side_effect = [mock_fail, mock_ok]
        files = get_modified_files(tmp_path, base_ref="main")
        assert files == {"models/staging/stg_orders.sql"}

    # 3. Fallback to HEAD~1
    with patch("subprocess.run") as mock_run:
        mock_fail = MagicMock(returncode=1)
        mock_ok = MagicMock(returncode=0, stdout="models/stg.sql\n")
        mock_run.side_effect = [mock_fail, mock_fail, mock_ok]
        files = get_modified_files(tmp_path, base_ref="main")
        assert files == {"models/stg.sql"}

    # 4. Exception
    with patch("subprocess.run", side_effect=RuntimeError("git failed")):
        files = get_modified_files(tmp_path, base_ref="main")
        assert files == set()


def test_is_finding_in_files() -> None:
    # Empty set
    finding = {"check": "c", "model": "dim_customers", "path": "models/marts/dim_customers.sql"}
    assert is_finding_in_files(finding, set(), _REPO_ROOT, _REPO_ROOT) is False

    # Match by exact path
    modified = {"models/marts/dim_customers.sql"}
    assert is_finding_in_files(finding, modified, _REPO_ROOT, _REPO_ROOT) is True

    # Match by model stem
    modified_stem = {"models/marts/marketing/dim_customers.sql"}
    assert is_finding_in_files(finding, modified_stem, _REPO_ROOT, _REPO_ROOT) is True

    # Project root outside repo root (triggers except Exception fallback)
    assert is_finding_in_files(
        {"check": "c", "model": "dim_customers", "path": "models/marts/dim_customers.sql"},
        {"models/marts/dim_customers.sql"},
        Path("/some/arbitrary/project"),
        Path("/other/repo"),
    ) is True

    # No match
    modified_other = {"models/staging/stg_orders.sql"}
    assert is_finding_in_files(finding, modified_other, _REPO_ROOT, _REPO_ROOT) is False


def test_generate_pr_comment_markdown_only_changed() -> None:
    current_data = {
        "overall_score": 95.0,
        "findings": [
            {"check": "c", "severity": "error", "message": "msg", "model": "m", "path": "p.sql"}
        ],
        "errors_count": 1,
        "warnings_count": 0,
        "category_scores": {},
    }
    md = generate_pr_comment_markdown(
        current_data,
        fail_under=80.0,
        fail_level="error",
        only_changed=True,
        modified_files_count=2,
        ignored_violations_count=5,
    )
    assert "Mode" in md
    assert "Gating `2` modified file(s)" in md
    assert "5 pre-existing violation(s) in unmodified files were excluded" in md


def test_execute_action_cli_only_changed_filters_violations(tmp_path: Path) -> None:
    # Minimal dbt project has 7 findings: 1 on dim_customers, 6 on staging/intermediate
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,
        fail_under=0.0,
        fail_level="error",
        only_changed=True,
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )

    with patch("tff.core.action.get_modified_files", return_value={"models/marts/marketing/dim_customers.sql"}):
        with patch("tff.core.action.render_health_report"):
            code = execute_action(args)
            # Only dim_customers violation remains, which has error severity -> fails with 1
            assert code == 1


def test_execute_action_cli_only_changed_no_matching_files() -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,
        fail_under=0.0,
        fail_level="error",
        only_changed=True,
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )

    # Modified file is unrelated (e.g. README.md) -> 0 gated violations -> passes with 0!
    with patch("tff.core.action.get_modified_files", return_value={"README.md"}):
        with patch("tff.core.action.render_health_report"):
            code = execute_action(args)
            assert code == 0


def test_cli_only_changed_flag() -> None:
    with patch("tff.core.action.get_modified_files", return_value={"README.md"}):
        assert main([
            "action",
            "--project", str(_MINIMAL_DBT),
            "--only-changed",
            "--no-annotations",
            "--fail-under", "0",
        ]) == 0


def test_execute_action_git_rev_parse_failure() -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,
        fail_under=0.0,
        fail_level="error",
        only_changed=True,
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )

    with patch("subprocess.run", side_effect=RuntimeError("git rev-parse failure")):
        with patch("tff.core.action.get_modified_files", return_value={"README.md"}):
            with patch("tff.core.action.render_health_report"):
                code = execute_action(args)
                assert code == 0



