"""Tests for tff GitHub Action runner, baseline diff, PR commenting, and action manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
from unittest.mock import MagicMock, patch
import urllib.error

import pytest
import yaml

from tff.core.action import (
    AUTOFIXABLE_CHECKS,
    PR_COMMENT_MARKER,
    REMEDIATION_SNIPPET,
    _format_finding_row,
    _git_clean_env,
    compare_findings,
    detect_pr_context,
    evaluate_pass_fail,
    evaluate_project,
    execute_action,
    fetch_base_scores,
    generate_pr_comment_markdown,
    get_finding_fingerprint,
    get_modified_files,
    is_autofixable,
    is_finding_in_files,
    parse_bool,
    post_or_update_pr_comment,
    write_github_output,
    write_github_step_summary,
)
from tff.core.cli import main
from conftest import _make_finding

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MINIMAL_DBT = _REPO_ROOT / "examples" / "minimal-dbt-project"


def test_action_yml_exists_and_matches_composite_manifest() -> None:
    root_manifest = _REPO_ROOT / "action.yml"
    sub_manifest = _REPO_ROOT / ".github" / "actions" / "tff" / "action.yml"

    assert root_manifest.is_file(), (
        "action.yml must exist at repository root for Marketplace publication"
    )
    assert sub_manifest.is_file(), ".github/actions/tff/action.yml must exist"

    root_content = yaml.safe_load(root_manifest.read_text(encoding="utf-8"))
    sub_content = yaml.safe_load(sub_manifest.read_text(encoding="utf-8"))

    assert root_content == sub_content, (
        "action.yml and .github/actions/tff/action.yml must match"
    )

    # Verify required Marketplace metadata
    assert root_content["name"] == "tff - Transformation Fitness Functions"
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
    finding_obj = _make_finding(
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
    assert resolved_viols2[0]["line"] == 10
    assert "col" in resolved_viols2[0]
    assert "end_line" in resolved_viols2[0]
    assert "end_col" in resolved_viols2[0]


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
    assert (
        evaluate_pass_fail(data_warnings, fail_under=80.0, fail_level="error") is True
    )
    assert (
        evaluate_pass_fail(data_warnings, fail_under=80.0, fail_level="warning")
        is False
    )

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
    md = generate_pr_comment_markdown(
        clean_data, base_data=None, fail_under=80.0, fail_level="error"
    )
    assert PR_COMMENT_MARKER in md
    assert "100.0%" in md
    assert "**tff Quality Gate Passed** — Health Score: 100.0%" in md
    assert "### DIMENSION DISTRIBUTION" not in md


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
        "category_scores": {
            "Connascence of Name (CoN)": 90.0,
            "Connascence of Algorithm (CoA)": 94.0,
        },
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

    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
    )
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
    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
    )
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
    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
    )
    assert "**tff Quality Gate Passed** — Health Score: 85.0% (0.0%)" in md


def test_post_or_update_pr_comment_no_token() -> None:
    res = post_or_update_pr_comment("", "owner/repo", 123, "body")
    assert res is None


def test_post_or_update_pr_comment_create_new() -> None:
    mock_list_resp = MagicMock()
    mock_list_resp.read.return_value = json.dumps(
        [
            {"id": 101, "body": "some other comment"},
        ]
    ).encode("utf-8")
    mock_list_resp.__enter__.return_value = mock_list_resp

    mock_post_resp = MagicMock()
    mock_post_resp.read.return_value = json.dumps({"id": 999}).encode("utf-8")
    mock_post_resp.__enter__.return_value = mock_post_resp

    with patch(
        "urllib.request.urlopen", side_effect=[mock_list_resp, mock_post_resp]
    ) as mock_open:
        cid = post_or_update_pr_comment("fake_token", "owner/repo", 42, "hello world")
        assert cid == 999
        assert mock_open.call_count == 2
        req2 = mock_open.call_args_list[1][0][0]
        assert req2.method == "POST"
        assert "42/comments" in req2.full_url


def test_post_or_update_pr_comment_update_existing() -> None:
    mock_list_resp = MagicMock()
    mock_list_resp.read.return_value = json.dumps(
        [
            {"id": 202, "body": f"old report\n{PR_COMMENT_MARKER}"},
        ]
    ).encode("utf-8")
    mock_list_resp.__enter__.return_value = mock_list_resp

    mock_patch_resp = MagicMock()
    mock_patch_resp.read.return_value = json.dumps({"id": 202}).encode("utf-8")
    mock_patch_resp.__enter__.return_value = mock_patch_resp

    with patch(
        "urllib.request.urlopen", side_effect=[mock_list_resp, mock_patch_resp]
    ) as mock_open:
        cid = post_or_update_pr_comment(
            "fake_token", "owner/repo", 42, "updated report"
        )
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
        json.dumps(
            {
                "pull_request": {"number": 88},
                "repository": {"full_name": "tjirab/tff"},
            }
        ),
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
        mock_run.side_effect = [
            mock_res1,
            MagicMock(returncode=0),
            mock_res_fail,
            mock_res_fail,
            MagicMock(returncode=0),
        ]
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
        assert "**tff Quality Gate Passed**" in summary_file.read_text(encoding="utf-8")


def test_execute_action_cli_with_annotations_and_findings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
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
    with patch(
        "tff.core.action.post_or_update_pr_comment", return_value=777
    ) as mock_post:
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
    assert "Run tff checks" in captured.out

    # Test passing execution
    assert (
        main(
            [
                "action",
                "--project",
                str(_MINIMAL_DBT),
                "--checks",
                "layer_integrity",
                "--no-annotations",
                "--fail-under",
                "0",
                "--fail-level",
                "error",
            ]
        )
        == 0
    )

    # Test failing execution
    assert (
        main(
            [
                "action",
                "--project",
                str(_MINIMAL_DBT),
                "--no-annotations",
                "--fail-under",
                "99.0",
            ]
        )
        == 1
    )


def test_fetch_base_scores_success(tmp_path: Path) -> None:
    # Setup dummy project inside temp dir
    proj_dir = tmp_path / "repo" / "my_project"
    proj_dir.mkdir(parents=True)

    dummy_scores = {"overall_score": 90.0, "findings": []}
    with (
        patch("subprocess.run") as mock_run,
        patch(
            "tff.core.action.evaluate_project", return_value=dummy_scores
        ) as mock_eval,
    ):
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
    mock_list_resp.read.return_value = json.dumps(
        [
            {"id": 303, "body": f"old report\n{PR_COMMENT_MARKER}"},
        ]
    ).encode("utf-8")
    mock_list_resp.__enter__.return_value = mock_list_resp

    with patch(
        "urllib.request.urlopen",
        side_effect=[mock_list_resp, RuntimeError("network drop")],
    ):
        cid = post_or_update_pr_comment(
            "fake_token", "owner/repo", 42, "updated report"
        )
        assert cid is None


def test_detect_pr_context_corrupted_json(tmp_path: Path) -> None:
    corrupt_file = tmp_path / "bad_event.json"
    corrupt_file.write_text("{ not valid json", encoding="utf-8")
    with patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(corrupt_file)}, clear=True):
        repo, pr = detect_pr_context()
        assert repo is None
        assert pr is None


def test_detect_pr_context_invalid_ref() -> None:
    with patch.dict(
        os.environ, {"GITHUB_REF": "refs/pull/notanumber/merge"}, clear=True
    ):
        repo, pr = detect_pr_context()
        assert repo is None
        assert pr is None


def test_github_env_helpers_exceptions() -> None:
    # Invalid paths triggering IOError
    with patch.dict(
        os.environ, {"GITHUB_OUTPUT": "/nonexistent_dir/impossible/out.txt"}
    ):
        write_github_output("key", "value")

    with patch.dict(
        os.environ, {"GITHUB_STEP_SUMMARY": "/nonexistent_dir/impossible/summary.md"}
    ):
        write_github_step_summary("summary content")


def test_execute_action_cli_with_base_diff_and_auto_pr(tmp_path: Path) -> None:
    event_file = tmp_path / "event.json"
    event_file.write_text(
        json.dumps(
            {
                "pull_request": {"number": 12},
                "repository": {"full_name": "tjirab/tff"},
            }
        ),
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

    with (
        patch("tff.core.action.fetch_base_scores", return_value=dummy_base_data),
        patch(
            "tff.core.action.post_or_update_pr_comment", return_value=888
        ) as mock_post,
        patch.dict(os.environ, {"GITHUB_EVENT_PATH": str(event_file)}),
    ):
        code = execute_action(args)
        assert code == 0
        mock_post.assert_called_once()
        assert mock_post.call_args[1]["repo"] == "tjirab/tff"
        assert mock_post.call_args[1]["pr_number"] == 12


def test_execute_action_comment_pr_no_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
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
        assert (
            "Notice: comment-pr is enabled, but could not detect pull request context"
            in captured.err
        )


def test_action_manifest_has_only_changed() -> None:
    root_manifest = _REPO_ROOT / "action.yml"
    root_content = yaml.safe_load(root_manifest.read_text(encoding="utf-8"))
    assert "only-changed" in root_content["inputs"]
    assert root_content["inputs"]["only-changed"]["default"] == "false"


def test_get_modified_files(tmp_path: Path) -> None:
    # 1. Success on origin/{base_ref}...HEAD
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="models/marts/dim_customers.sql\nmodels/staging/stg_orders.sql\n",
        )
        files = get_modified_files(tmp_path, base_ref="main")
        assert files == {
            "models/marts/dim_customers.sql",
            "models/staging/stg_orders.sql",
        }

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
    finding = {
        "check": "c",
        "model": "dim_customers",
        "path": "models/marts/dim_customers.sql",
    }
    assert is_finding_in_files(finding, set(), _REPO_ROOT, _REPO_ROOT) is False

    # Match by exact path
    modified = {"models/marts/dim_customers.sql"}
    assert is_finding_in_files(finding, modified, _REPO_ROOT, _REPO_ROOT) is True

    # Match by model stem
    modified_stem = {"models/marts/marketing/dim_customers.sql"}
    assert is_finding_in_files(finding, modified_stem, _REPO_ROOT, _REPO_ROOT) is True

    # Project root outside repo root (triggers except Exception fallback)
    assert (
        is_finding_in_files(
            {
                "check": "c",
                "model": "dim_customers",
                "path": "models/marts/dim_customers.sql",
            },
            {"models/marts/dim_customers.sql"},
            Path("/some/arbitrary/project"),
            Path("/other/repo"),
        )
        is True
    )

    # No match
    modified_other = {"models/staging/stg_orders.sql"}
    assert is_finding_in_files(finding, modified_other, _REPO_ROOT, _REPO_ROOT) is False


def test_generate_pr_comment_markdown_only_changed() -> None:
    current_data = {
        "overall_score": 95.0,
        "findings": [
            {
                "check": "c",
                "severity": "error",
                "message": "msg",
                "model": "m",
                "path": "p.sql",
            }
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

    with patch(
        "tff.core.action.get_modified_files",
        return_value={"models/marts/marketing/dim_customers.sql"},
    ):
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
        assert (
            main(
                [
                    "action",
                    "--project",
                    str(_MINIMAL_DBT),
                    "--only-changed",
                    "--no-annotations",
                    "--fail-under",
                    "0",
                ]
            )
            == 0
        )


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


def test_evaluate_project_with_workers() -> None:
    res = evaluate_project(_MINIMAL_DBT, workers=2)
    assert res["config"].workers == 2
    assert "overall_score" in res["scores"]


def test_evaluate_project_with_chunk_size() -> None:
    res = evaluate_project(_MINIMAL_DBT, chunk_size=4)
    assert res["config"].chunk_size == 4
    assert "overall_score" in res["scores"]


def test_execute_action_annotations_with_modified_files(capsys) -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,
        fail_under=0.0,
        fail_level="error",
        only_changed=False,
        comment_pr="false",
        github_token=None,
        base_ref="main",
        diff_against_base=False,
        annotations=True,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )
    with (
        patch("subprocess.run", side_effect=RuntimeError("git rev-parse error")),
        patch(
            "tff.core.action.get_modified_files",
            return_value={"models/staging/stg_orders.sql"},
        ),
        patch("tff.core.action.render_health_report"),
    ):
        code = execute_action(args)
        assert code == 1
        captured = capsys.readouterr()
        assert "::error" in captured.out


def test_evaluate_project_with_scoped_models() -> None:
    res = evaluate_project(
        _MINIMAL_DBT,
        scoped_models={"model.minimal_dbt_project.stg_orders"},
    )
    assert "overall_score" in res["scores"]
    assert res["models_checked"] == 1


def test_execute_action_only_changed_scopes_models() -> None:
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
        base_ref="main",
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )
    with (
        patch("subprocess.run", side_effect=RuntimeError("git rev-parse error")),
        patch(
            "tff.core.action.get_modified_files",
            return_value={"models/staging/stg_orders.sql"},
        ),
        patch("tff.core.action.render_health_report"),
    ):
        code = execute_action(args)
        # Should execute successfully and evaluate scoped models
        assert code in (0, 1)


def test_execute_action_only_changed_scope_exception() -> None:
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
        base_ref="main",
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=False,
    )
    with (
        patch("subprocess.run", side_effect=RuntimeError("git rev-parse error")),
        patch(
            "tff.core.action.get_modified_files",
            return_value={"models/staging/stg_orders.sql"},
        ),
        patch(
            "tff.core.adapter.get_adapter",
            side_effect=RuntimeError("Adapter load error"),
        ),
        patch("tff.core.action.render_health_report"),
    ):
        code = execute_action(args)
        assert code in (0, 1)


def test_evaluate_project_multiple_roots(tmp_path: Path) -> None:
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    shutil.copytree(_MINIMAL_DBT, p1)
    shutil.copytree(_MINIMAL_DBT, p2)
    res = evaluate_project([p1, p2], provider="dbt")
    assert res["provider"] == "dbt"
    assert res["models_checked"] == 8
    assert res["overall_score"] > 0.0
    assert res["project_roots"] == [str(p1), str(p2)]


def test_execute_action_multi_project_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    shutil.copytree(_MINIMAL_DBT, p1)
    shutil.copytree(_MINIMAL_DBT, p2)
    args = argparse.Namespace(
        projects=[p1, p2],
        project=None,
        provider="dbt",
        config="fitness_functions.yaml",
        checks="layer_integrity",
        fail_under=0.0,
        fail_level="error",
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=True,
    )
    code = execute_action(args)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "project_roots" in data
    assert data["project_roots"] == [str(p1), str(p2)]
    assert data["current"]["models_checked"] == 8


def test_execute_action_multi_project_annotations(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    shutil.copytree(_MINIMAL_DBT, p1)
    shutil.copytree(_MINIMAL_DBT, p2)
    args = argparse.Namespace(
        projects=[p1, p2],
        project=None,
        provider="dbt",
        config="fitness_functions.yaml",
        checks=None,
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
    code = execute_action(args)
    assert code == 1
    captured = capsys.readouterr()
    assert "::error file=" in captured.out


def test_execute_action_multi_project_only_changed(tmp_path: Path) -> None:
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    shutil.copytree(_MINIMAL_DBT, p1)
    shutil.copytree(_MINIMAL_DBT, p2)
    args = argparse.Namespace(
        projects=[p1, p2],
        project=None,
        provider="dbt",
        config="fitness_functions.yaml",
        checks=None,
        fail_under=0.0,
        fail_level="error",
        comment_pr="false",
        github_token=None,
        base_ref="main",
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=True,
        only_changed=True,
    )
    # 1. When modified file is unrelated (e.g. README.md) -> 0 violations gated -> passes with 0
    with (
        patch("subprocess.run") as mock_subproc,
        patch("tff.core.action.get_modified_files", return_value={"README.md"}),
    ):
        mock_subproc.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout=str(tmp_path.resolve()) + "\n", returncode=0)
            if "rev-parse" in cmd
            else MagicMock(returncode=0)
        )
        code = execute_action(args)
        assert code == 0

    # 2. When modified file belongs to proj2 model with violations -> fails with 1
    with (
        patch("subprocess.run") as mock_subproc,
        patch(
            "tff.core.action.get_modified_files",
            return_value={"proj2/models/staging/stg_orders.sql"},
        ),
    ):
        mock_subproc.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout=str(tmp_path.resolve()) + "\n", returncode=0)
            if "rev-parse" in cmd
            else MagicMock(returncode=0)
        )
        code_fail = execute_action(args)
        assert code_fail == 1


def test_fetch_base_scores_multi_project(tmp_path: Path) -> None:
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    p1.mkdir()
    p2.mkdir()
    dummy_scores = {"overall_score": 95.0, "findings": []}
    with (
        patch("subprocess.run") as mock_subproc,
        patch("tempfile.mkdtemp", return_value=str(tmp_path / "temp-base")),
        patch(
            "tff.core.action.evaluate_project", return_value=dummy_scores
        ) as mock_eval,
    ):
        mock_subproc.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout=str(tmp_path.resolve()) + "\n", returncode=0)
            if "rev-parse" in cmd
            else MagicMock(returncode=0)
        )
        temp_base = tmp_path / "temp-base"
        (temp_base / "proj1").mkdir(parents=True)
        (temp_base / "proj2").mkdir(parents=True)

        res = fetch_base_scores([p1, p2], base_ref="main")
        assert res == dummy_scores
        mock_eval.assert_called_once()
        called_roots = mock_eval.call_args.kwargs["project_root"]
        assert len(called_roots) == 2


def test_fetch_base_scores_multi_project_none_exist(tmp_path: Path) -> None:
    p1 = tmp_path / "proj1"
    p2 = tmp_path / "proj2"
    p1.mkdir()
    p2.mkdir()
    with (
        patch("subprocess.run") as mock_subproc,
        patch("tempfile.mkdtemp", return_value=str(tmp_path / "temp-base-empty")),
    ):
        mock_subproc.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout=str(tmp_path.resolve()) + "\n", returncode=0)
            if "rev-parse" in cmd
            else MagicMock(returncode=0)
        )
        res = fetch_base_scores([p1, p2], base_ref="main")
        assert res is None


def test_fetch_base_scores_multi_project_outside_repo(tmp_path: Path) -> None:
    p1 = tmp_path / "repo" / "proj1"
    p1.mkdir(parents=True)
    p_outside = Path("/other/outside/directory")
    dummy_scores = {"overall_score": 95.0, "findings": []}
    with (
        patch("subprocess.run") as mock_subproc,
        patch("tempfile.mkdtemp", return_value=str(tmp_path / "temp-base")),
        patch(
            "tff.core.action.evaluate_project", return_value=dummy_scores
        ) as mock_eval,
    ):
        mock_subproc.side_effect = lambda cmd, **kwargs: (
            MagicMock(stdout=str((tmp_path / "repo").resolve()) + "\n", returncode=0)
            if "rev-parse" in cmd
            else MagicMock(returncode=0)
        )
        temp_base = tmp_path / "temp-base"
        (temp_base / "proj1").mkdir(parents=True)

        res = fetch_base_scores([p1, p_outside], base_ref="main")
        assert res == dummy_scores
        mock_eval.assert_called_once()
        called_roots = mock_eval.call_args.kwargs["project_root"]
        assert called_roots == [temp_base / "proj1"]


def test_execute_action_project_as_list_and_fallback_cwd() -> None:
    # 1. args.project as list (line 695)
    args_list = argparse.Namespace(
        project=[_MINIMAL_DBT],
        projects=None,
        provider="dbt",
        config="fitness_functions.yaml",
        checks="layer_integrity",
        fail_under=0.0,
        fail_level="error",
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=True,
    )
    code = execute_action(args_list)
    assert code == 0

    # 2. Both projects and project are None (fallback to Path.cwd(), line 699)
    args_none = argparse.Namespace(
        project=None,
        projects=None,
        provider="dbt",
        config="fitness_functions.yaml",
        checks="layer_integrity",
        fail_under=0.0,
        fail_level="error",
        comment_pr="false",
        github_token=None,
        base_ref=None,
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=True,
    )
    with patch(
        "tff.core.action.evaluate_project",
        return_value={
            "overall_score": 100.0,
            "findings": [],
            "errors_count": 0,
            "warnings_count": 0,
            "scores": {},
            "config": MagicMock(),
            "provider": "dbt",
        },
    ):
        code_none = execute_action(args_none)
        assert code_none == 0


@pytest.mark.parametrize(
    ("check", "message", "expected"),
    [
        ("banselectstar", "SELECT * is prohibited", False),
        ("ban_select_star", "SELECT * is prohibited", False),
        ("nopositionalgroupby", "Positional GROUP BY prohibited", False),
        ("nopositionalorderby", "Positional ORDER BY prohibited", False),
        ("nopositionalgroupbyororderby", "Positional GROUP BY prohibited", False),
        ("nomissingowner", "Missing model owner", False),
        ("nomissingdescription", "Missing model description", False),
        ("martmodelnamingconvention", "Invalid mart model name", False),
        ("mart_naming", "Invalid mart model name", False),
        ("filenameequalsmodelname", "Filename mismatch", True),
        ("filename_equals_modelname", "Filename mismatch", True),
        (
            "sqlcomplexity",
            "Complex query with nested subquery in final SELECT",
            False,
        ),
        ("sqlcomplexity", "Too many CTEs in model", False),
        ("layer_integrity", "Upstream layer dependency violated", False),
        ("join_type_parity", "Mismatched join types", False),
        ("unknown_check", "Unknown violation", False),
    ],
)
def test_is_autofixable_checks(check: str, message: str, expected: bool) -> None:
    dict_finding = {"check": check, "message": message}
    obj_finding = _make_finding(
        check=check, severity="error", message=message, model="orders"
    )
    assert is_autofixable(dict_finding) is expected
    assert is_autofixable(obj_finding) is expected


@pytest.mark.parametrize(
    ("is_fixable", "expected"),
    [
        (True, True),
        (False, False),
    ],
)
def test_is_autofixable_dynamic_registry(is_fixable: bool, expected: bool) -> None:
    from tff.core.registry import CheckDefinition, registry

    custom_id = f"custom_action_rule_{is_fixable}"
    registry.register(
        CheckDefinition(
            id=custom_id,
            label="Custom Action Rule",
            category="Custom Rules",
            scope="model",
            is_fixable=is_fixable,
        )
    )
    try:
        dict_finding = {"check": custom_id, "message": "Custom violation"}
        obj_finding = _make_finding(
            check=custom_id,
            severity="error",
            message="Custom violation",
            model="orders",
        )
        assert is_autofixable(dict_finding) is expected
        assert is_autofixable(obj_finding) is expected
    finally:
        registry.unregister(custom_id)


def test_generate_pr_comment_diff_first_triage_callout() -> None:
    current_data = {
        "overall_score": 78.0,
        "findings": [
            {
                "check": "filenameequalsmodelname",
                "severity": "error",
                "message": "Model name does not match filename",
                "model": "stg_orders",
                "path": "models/staging/stg_orders.sql",
            },
            {
                "check": "layer_integrity",
                "severity": "error",
                "message": "Direct marts access prohibited",
                "model": "dim_customers",
                "path": "models/marts/dim_customers.sql",
            },
            {
                "check": "nomissingowner",
                "severity": "warning",
                "message": "Owner required",
                "model": "stg_orders",
                "path": "models/staging/stg_orders.sql",
            },
        ],
        "errors_count": 2,
        "warnings_count": 1,
        "category_scores": {},
    }
    base_data = {
        "overall_score": 85.0,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
    }

    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
        modified_files={
            "models/staging/stg_orders.sql",
            "models/marts/dim_customers.sql",
        },
    )

    # 1. Callout box at top
    assert "> [!CAUTION]" in md
    assert "> ### New Violations Introduced in This PR" in md

    # 2. Grouped by touched model file first (dim_customers before stg_orders, error before warning)
    dim_pos = md.find("dim_customers")
    stg_pos = md.find("stg_orders")
    assert dim_pos != -1 and stg_pos != -1
    assert dim_pos < stg_pos

    # 3. Autofixable badge and copyable remediation snippet
    assert "`[Autofixable]`" in md
    assert "tff lint --fix --staged" in md


def test_generate_pr_comment_collapsible_baseline_debt() -> None:
    current_data = {
        "overall_score": 82.0,
        "findings": [
            {
                "check": "nomissingowner",
                "severity": "warning",
                "message": "Missing owner",
                "model": "untouched_dim",
                "path": "models/marts/untouched_dim.sql",
            },
            {
                "check": "banselectstar",
                "severity": "error",
                "message": "SELECT * in touched model",
                "model": "touched_model",
                "path": "models/staging/touched_model.sql",
            },
            {
                "check": "duplicate_ctes",
                "severity": "warning",
                "message": "Duplicate CTE in touched path",
                "model": None,
                "path": "models/staging/touched_model.sql",
            },
        ],
        "errors_count": 1,
        "warnings_count": 1,
        "category_scores": {},
    }
    base_data = {
        "overall_score": 85.0,
        "findings": [
            {
                "check": "nomissingowner",
                "severity": "warning",
                "message": "Missing owner",
                "model": "untouched_dim",
                "path": "models/marts/untouched_dim.sql",
            },
            {
                "check": "duplicate_ctes",
                "severity": "warning",
                "message": "Duplicate CTE in touched path",
                "model": None,
                "path": "models/staging/touched_model.sql",
            },
        ],
        "errors_count": 0,
        "warnings_count": 2,
    }

    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
        modified_files={"models/staging/touched_model.sql"},
    )

    # Untouched baseline debt collapsed into closed details
    assert (
        "<summary>View 1 pre-existing violations across untouched models</summary>"
        in md
    )
    # Must NOT have <details open> for untouched debt
    assert (
        "<details>\n<summary>View 1 pre-existing violations across untouched models</summary>"
        in md
    )


@pytest.mark.parametrize(
    ("score", "base_score", "expected_card"),
    [
        (96.2, 95.4, "**tff Quality Gate Passed** — Health Score: 96.2% (+0.8%)"),
        (90.0, 92.5, "**tff Quality Gate Passed** — Health Score: 90.0% (-2.5%)"),
        (85.0, 85.0, "**tff Quality Gate Passed** — Health Score: 85.0% (0.0%)"),
    ],
)
def test_generate_pr_comment_compact_green_pass_card(
    score: float, base_score: float, expected_card: str
) -> None:
    current_data = {
        "overall_score": score,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
        "category_scores": {},
    }
    base_data = {
        "overall_score": base_score,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
    }
    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
    )
    assert PR_COMMENT_MARKER in md
    assert expected_card in md
    assert "### DIMENSION DISTRIBUTION" not in md


def test_generate_pr_comment_pass_with_baseline_debt() -> None:
    """When all checks pass and no new violations exist, render pass card + collapsible baseline debt."""
    pre_existing_finding = {
        "check": "filenameequalsmodelname",
        "severity": "warning",
        "message": "Filename mismatch on legacy model",
        "model": "legacy_untouched",
        "path": "models/legacy_untouched.sql",
    }
    current_data = {
        "overall_score": 96.2,
        "findings": [pre_existing_finding],
        "errors_count": 0,
        "warnings_count": 1,
        "category_scores": {},
    }
    base_data = {
        "overall_score": 95.4,
        "findings": [pre_existing_finding],
        "errors_count": 0,
        "warnings_count": 1,
    }
    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
        modified_files={"models/marts/new_feature.sql"},
    )
    # Celebratory badge card
    assert "**tff Quality Gate Passed** — Health Score: 96.2% (+0.8%)" in md
    # Closed details baseline debt
    assert (
        "<summary>View 1 pre-existing violations across untouched models</summary>"
        in md
    )
    # Remediation snippet
    assert "tff lint --fix --staged" in md


@pytest.mark.parametrize(
    (
        "scenario",
        "base_data_present",
        "modified_files",
        "expected_header",
        "expected_detail",
    ),
    [
        (
            "touched_warning_base_none",
            False,
            {"models/int_protolabs_activities.sql"},
            "## ■ ▲ ● TFF ARCHITECTURE AUDIT",
            "### Violations Detail (1)",
        ),
        (
            "touched_warning_base_present",
            True,
            {"models/int_protolabs_activities.sql"},
            "## ■ ▲ ● TFF ARCHITECTURE AUDIT",
            "### Violations Detail (1)",
        ),
        (
            "unmodified_findings_base_none",
            False,
            {"models/other_clean_model.sql"},
            "## ■ ▲ ● TFF ARCHITECTURE AUDIT",
            "View 1 pre-existing violations across untouched models",
        ),
    ],
)
def test_generate_pr_comment_suppresses_compact_pass_when_violations_exist(
    scenario: str,
    base_data_present: bool,
    modified_files: set[str],
    expected_header: str,
    expected_detail: str,
) -> None:
    """Findings on modified models or missing baseline must render the full audit report, not compact pass card."""
    finding = _make_finding(
        check="connascence_of_value",
        severity="warning",
        message="Connascence of value: literal 'protolabs'",
        model="int_protolabs_activities",
        path="models/int_protolabs_activities.sql",
    )
    current_data = {
        "overall_score": 98.9,
        "findings": [finding],
        "errors_count": 0,
        "warnings_count": 1,
        "category_scores": {},
    }
    base_data = (
        {
            "overall_score": 98.9,
            "findings": [finding],
            "errors_count": 0,
            "warnings_count": 1,
        }
        if base_data_present
        else None
    )

    md = generate_pr_comment_markdown(
        current_data,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
        modified_files=modified_files,
    )
    assert expected_header in md
    assert expected_detail in md
    assert "int_protolabs_activities" in md
    assert not md.startswith(f"{PR_COMMENT_MARKER}\n**tff Quality Gate Passed**")


def test_fetch_base_scores_accepts_manifest_dialect_workers(tmp_path: Path) -> None:
    """Ensure fetch_base_scores forwards dialect, manifest, and workers to evaluate_project."""
    manifest_file = tmp_path / "base_manifest.json"
    manifest_file.write_text("{}", encoding="utf-8")

    with (
        patch("tff.core.action.evaluate_project") as mock_eval,
        patch("tff.core.action.subprocess.run") as mock_run,
    ):
        mock_run.return_value = MagicMock(returncode=0, stdout=str(tmp_path))
        (tmp_path / "fitness_functions.yaml").write_text(
            "version: 1\n", encoding="utf-8"
        )

        fetch_base_scores(
            tmp_path,
            base_ref="main",
            provider="dbt",
            dialect="duckdb",
            manifest=manifest_file,
            workers=4,
        )
        assert mock_eval.called
        kwargs = mock_eval.call_args.kwargs
        assert kwargs.get("dialect") == "duckdb"
        assert kwargs.get("manifest") == manifest_file.resolve()
        assert kwargs.get("workers") == 4


def test_execute_action_forwards_base_manifest(tmp_path: Path) -> None:
    """Ensure execute_action parses and passes base_manifest to fetch_base_scores."""
    base_manifest = tmp_path / "base_manifest.json"
    base_manifest.write_text("{}", encoding="utf-8")

    args = argparse.Namespace(
        project=tmp_path,
        projects=None,
        provider="auto",
        config="fitness_functions.yaml",
        checks=None,
        dialect="duckdb",
        manifest=None,
        base_manifest=base_manifest,
        base_ref="main",
        diff_against_base=True,
        workers=2,
        fail_under=0.0,
        fail_level="error",
        only_changed=False,
        annotations=False,
        comment_pr="false",
        json=True,
    )

    with (
        patch("tff.core.action.evaluate_project") as mock_eval,
        patch("tff.core.action.fetch_base_scores") as mock_fetch,
        patch("tff.core.action.get_modified_files", return_value=set()),
    ):
        mock_eval.return_value = {
            "overall_score": 100.0,
            "findings": [],
            "errors_count": 0,
            "warnings_count": 0,
        }
        mock_fetch.return_value = None
        code = execute_action(args)
        assert code == 0
        assert mock_fetch.called
        assert mock_fetch.call_args.kwargs.get("manifest") == base_manifest
        assert mock_fetch.call_args.kwargs.get("dialect") == "duckdb"
        assert mock_fetch.call_args.kwargs.get("workers") == 2


def test_generate_pr_comment_zero_emoji_guarantee() -> None:
    """Ensure zero decorative emojis appear in any generated PR comments per revised style guide."""
    prohibited_emojis = ["📁", "🔧", "📈", "📉", "🚀", "🎉", "❌", "⚠️", "✅"]
    test_data = {
        "overall_score": 96.2,
        "findings": [
            {
                "check": "banselectstar",
                "severity": "error",
                "message": "SELECT * prohibited",
                "model": "model_a",
                "path": "models/model_a.sql",
            }
        ],
        "errors_count": 1,
        "warnings_count": 0,
        "category_scores": {},
    }
    md = generate_pr_comment_markdown(test_data, base_data=None, fail_under=80.0)
    for emoji in prohibited_emojis:
        assert emoji not in md, f"Prohibited emoji '{emoji}' found in PR comment"


def test_format_finding_row_types() -> None:
    finding_obj = _make_finding(
        check="filenameequalsmodelname",
        severity="error",
        message="Filename does not match model name",
        model="stg_orders",
        path=Path("models/staging/stg_orders.sql"),
    )
    row_obj = _format_finding_row(finding_obj)
    assert "`ERR`" in row_obj
    assert "`stg_orders`" in row_obj
    assert "`[Autofixable]`" in row_obj

    finding_obj_no_model = _make_finding(
        check="columnnames",
        severity="warning",
        message="Invalid column",
        model=None,
        path=Path("models/marts/dim_users.sql"),
    )
    row_no_model = _format_finding_row(finding_obj_no_model)
    assert "`WRN`" in row_no_model
    assert "models/marts/dim_users.sql" in row_no_model

    finding_dict = {
        "check": "nomissingowner",
        "severity": "warning",
        "message": "Missing owner",
        "model": "dim_users",
    }
    row_dict = _format_finding_row(finding_dict)
    assert "`WRN`" in row_dict
    assert "`dim_users`" in row_dict

    finding_newlines = _make_finding(
        check="columnnames",
        severity="warning",
        message="Invalid\r\ncolumn\rwith\nwhitespace",
        model="stg_orders",
    )
    row_newlines = _format_finding_row(finding_newlines)
    assert "\r" not in row_newlines
    assert "\n" not in row_newlines
    assert "Invalid column with whitespace" in row_newlines


def test_generate_pr_comment_collapsible_baseline_debt_truncation() -> None:
    """Test truncation of pre-existing violations across untouched models when > 50."""
    pre_existing_55 = [
        {
            "check": "filenameequalsmodelname",
            "severity": "warning",
            "message": f"Missing owner on legacy model {i}",
            "model": f"legacy_model_{i}",
            "path": f"models/legacy_model_{i}.sql",
        }
        for i in range(55)
    ]
    # 1. In pass mode (> 50 truncated)
    current_pass = {
        "overall_score": 95.0,
        "findings": pre_existing_55,
        "errors_count": 0,
        "warnings_count": 55,
        "category_scores": {},
    }
    base_data = {
        "overall_score": 95.0,
        "findings": pre_existing_55,
        "errors_count": 0,
        "warnings_count": 55,
    }
    md_pass = generate_pr_comment_markdown(
        current_pass,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
        modified_files={"models/marts/feature.sql"},
    )
    assert "View 55 pre-existing violations across untouched models" in md_pass
    assert "... and 5 more pre-existing violations truncated." in md_pass

    # 2. In fail mode (> 50 truncated)
    current_fail = {
        "overall_score": 70.0,
        "findings": pre_existing_55,
        "errors_count": 0,
        "warnings_count": 55,
        "category_scores": {},
    }
    md_fail = generate_pr_comment_markdown(
        current_fail,
        base_data=base_data,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
        modified_files={"models/marts/feature.sql"},
    )
    assert "View 55 pre-existing violations across untouched models" in md_fail
    assert "... and 5 more pre-existing violations truncated." in md_fail


def test_generate_pr_comment_untouched_no_modified_files() -> None:
    """When base_data is present, modified_files=None, and 0 new violations exist, all pre-existing findings are untouched."""
    pre_existing = [
        {
            "check": "nomissingowner",
            "severity": "warning",
            "message": "Missing owner on model",
            "model": "model_x",
            "path": "models/model_x.sql",
        }
    ]
    current = {
        "overall_score": 95.0,
        "findings": pre_existing,
        "errors_count": 0,
        "warnings_count": 1,
        "category_scores": {},
    }
    base = {
        "overall_score": 95.0,
        "findings": pre_existing,
        "errors_count": 0,
        "warnings_count": 1,
    }
    md = generate_pr_comment_markdown(
        current,
        base_data=base,
        fail_under=80.0,
        fail_level="error",
        base_ref="main",
        modified_files=None,
    )
    assert "View 1 pre-existing violations across untouched models" in md


def test_autofixable_constants() -> None:
    assert "filenameequalsmodelname" in AUTOFIXABLE_CHECKS
    assert "filename_equals_modelname" in AUTOFIXABLE_CHECKS
    assert "tff lint --fix --staged" in REMEDIATION_SNIPPET


@pytest.mark.parametrize(
    "git_env_var",
    [
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_INDEX_FILE",
        "GIT_COMMON_DIR",
        "GIT_PREFIX",
        "GIT_OBJECT_DIRECTORY",
    ],
)
def test_git_clean_env_sanitizes_variables(git_env_var: str, tmp_path: Path) -> None:
    with patch.dict(
        os.environ,
        {git_env_var: "/leaked/git/path", "KEEP_VAR": "preserved"},
    ):
        cleaned = _git_clean_env()
        assert git_env_var not in cleaned
        assert cleaned.get("KEEP_VAR") == "preserved"

        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="models/a.sql\n")
            get_modified_files(tmp_path, base_ref="main")
            called_env = mock_run.call_args.kwargs.get("env")
            assert called_env is not None
            assert git_env_var not in called_env


@pytest.mark.parametrize("only_changed", [False, True])
def test_execute_action_invokes_get_modified_files_once_and_sanitizes_git_env(
    only_changed: bool,
) -> None:
    args = argparse.Namespace(
        project=_MINIMAL_DBT,
        provider="auto",
        config="fitness_functions.yaml",
        checks="layer_integrity",
        fail_under=0.0,
        fail_level="error",
        only_changed=only_changed,
        comment_pr="false",
        github_token=None,
        base_ref="main",
        diff_against_base=False,
        annotations=False,
        pr_number=None,
        repo=None,
        dialect=None,
        manifest=None,
        json=True,
    )
    leaked_env = {
        "GIT_DIR": "/fake/.git",
        "GIT_WORK_TREE": "/fake/wt",
        "GIT_INDEX_FILE": "/fake/index",
        "GIT_COMMON_DIR": "/fake/common",
    }
    with (
        patch.dict(os.environ, leaked_env),
        patch("subprocess.run") as mock_subproc,
        patch(
            "tff.core.action.get_modified_files", return_value={"README.md"}
        ) as mock_get_modified,
    ):
        mock_subproc.return_value = MagicMock(
            returncode=0, stdout=str(_REPO_ROOT) + "\n"
        )
        code = execute_action(args)
        assert code == 0
        mock_get_modified.assert_called_once()
        mock_subproc.assert_called_once()
        called_env = mock_subproc.call_args.kwargs.get("env")
        assert called_env is not None
        for var in leaked_env:
            assert var not in called_env
