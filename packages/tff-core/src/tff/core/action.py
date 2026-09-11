"""GitHub Action runner, baseline diff calculator, and PR comment generator for TFF."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import urllib.error
import urllib.request

from tff.core.adapter import detect_provider, get_adapter
from tff.core.config import load_fitness_config
from tff.core.formatters import emit_github_annotations
from tff.core.health import calculate_health_scores, render_health_report
from tff.core.report import LintFinding

logger = logging.getLogger(__name__)

PR_COMMENT_MARKER = "<!-- tff-pr-comment -->"


def parse_bool(val: Any) -> bool:
    """Parse string or boolean value to boolean."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in ("true", "1", "yes", "on")
    return bool(val)


def get_finding_fingerprint(
    finding: dict[str, Any] | LintFinding,
) -> tuple[str, str, str]:
    """Return a unique tuple identifying a finding for diff comparison."""
    if isinstance(finding, LintFinding):
        check = str(finding.check)
        model = str(finding.model or "")
        msg = str(finding.message)
    else:
        check = str(finding.get("check", ""))
        model = str(finding.get("model", "") or "")
        msg = str(finding.get("message", ""))
    return (check, model, msg)


def compare_findings(
    current_findings: list[dict[str, Any] | LintFinding],
    base_findings: list[dict[str, Any] | LintFinding],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare current and base findings to determine new and resolved violations."""
    base_fps = {get_finding_fingerprint(f) for f in base_findings}
    curr_fps = {get_finding_fingerprint(f) for f in current_findings}

    def _to_dict(f: dict[str, Any] | LintFinding) -> dict[str, Any]:
        if isinstance(f, LintFinding):
            return {
                "check": f.check,
                "severity": f.severity,
                "message": f.message,
                "model": f.model,
                "path": str(f.path) if f.path else None,
                "line": f.line,
            }
        return dict(f)

    new_findings = [
        _to_dict(f)
        for f in current_findings
        if get_finding_fingerprint(f) not in base_fps
    ]
    resolved_findings = [
        _to_dict(f)
        for f in base_findings
        if get_finding_fingerprint(f) not in curr_fps
    ]
    return new_findings, resolved_findings


def evaluate_project(
    project_root: Path,
    provider: str = "auto",
    config_path: str = "fitness_functions.yaml",
    checks: list[str] | None = None,
    dialect: str | None = None,
    manifest: Path | None = None,
) -> dict[str, Any]:
    """Run TFF health evaluation on the specified project directory."""
    project_root = Path(project_root).resolve()
    if provider == "auto":
        provider = detect_provider(project_root)

    adapter = get_adapter(provider)
    config = load_fitness_config(project_root, config_path=config_path)

    findings, models_checked, executed_checks = adapter.run_checks(
        project_root=project_root,
        config=config,
        checks=checks,
        dialect=dialect,
        manifest_path=manifest,
    )

    scores = calculate_health_scores(findings, models_checked, config, provider)

    finding_dicts: list[dict[str, Any]] = [
        {
            "check": f.check,
            "severity": f.severity,
            "message": f.message,
            "model": f.model,
            "path": str(f.path) if f.path else None,
            "line": f.line,
        }
        for f in findings
    ]

    errors_count = sum(1 for f in findings if f.severity == "error")
    warnings_count = sum(1 for f in findings if f.severity == "warning")

    return {
        "overall_score": float(scores.get("overall_score", 100.0)),
        "models_checked": models_checked,
        "category_scores": scores.get("category_scores", {}),
        "check_scores": scores.get("check_scores", {}),
        "findings": finding_dicts,
        "raw_findings": findings,
        "errors_count": errors_count,
        "warnings_count": warnings_count,
        "provider": provider,
        "scores": scores,
        "config": config,
    }


def evaluate_pass_fail(
    data: dict[str, Any],
    fail_under: float = 0.0,
    fail_level: str = "error",
) -> bool:
    """Determine whether the project meets quality and health thresholds."""
    overall_score = float(data.get("overall_score", 100.0))
    if fail_under > 0.0 and overall_score < fail_under:
        return False

    errors_count = int(data.get("errors_count", 0))
    warnings_count = int(data.get("warnings_count", 0))

    if fail_level.lower() == "warning":
        if errors_count > 0 or warnings_count > 0:
            return False
    else:  # default "error"
        if errors_count > 0:
            return False

    return True


def fetch_base_scores(
    project_dir: Path,
    base_ref: str,
    provider: str = "auto",
    config_path: str = "fitness_functions.yaml",
    checks: list[str] | None = None,
) -> dict[str, Any] | None:
    """Attempt to checkout base_ref in a temp git worktree and calculate baseline health score."""
    project_dir = Path(project_dir).resolve()
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(project_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        repo_root = Path(res.stdout.strip()).resolve()
        rel_project = project_dir.relative_to(repo_root)
    except Exception as e:
        logger.debug("Failed to find git repo root: %s", e)
        return None

    temp_dir = tempfile.mkdtemp(prefix="tff-base-")
    try:
        subprocess.run(
            ["git", "fetch", "origin", base_ref, "--depth=1"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )

        target_ref = f"origin/{base_ref}"
        worktree_cmd = [
            "git",
            "worktree",
            "add",
            "--detach",
            temp_dir,
            target_ref,
        ]
        res = subprocess.run(
            worktree_cmd, cwd=str(repo_root), capture_output=True, text=True
        )
        if res.returncode != 0:
            worktree_cmd[-1] = base_ref
            res = subprocess.run(
                worktree_cmd, cwd=str(repo_root), capture_output=True, text=True
            )
            if res.returncode != 0:
                logger.debug("git worktree add failed: %s", res.stderr)
                return None

        base_project_dir = Path(temp_dir) / rel_project
        if not base_project_dir.exists():
            logger.debug(
                "Base project path does not exist in base ref: %s",
                base_project_dir,
            )
            return None

        return evaluate_project(
            project_root=base_project_dir,
            provider=provider,
            config_path=config_path,
            checks=checks,
        )
    except Exception as e:
        logger.debug("Error calculating base scores: %s", e)
        return None
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", temp_dir],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_pr_comment_markdown(
    current_data: dict[str, Any],
    base_data: dict[str, Any] | None = None,
    fail_under: float = 0.0,
    fail_level: str = "error",
    base_ref: str = "main",
) -> str:
    """Generate the GitHub PR markdown comment summarizing health score and violations."""
    score = float(current_data.get("overall_score", 100.0))
    passed = evaluate_pass_fail(
        current_data, fail_under=fail_under, fail_level=fail_level
    )
    status_badge = "🟢 **PASSED**" if passed else "🔴 **FAILED**"

    total_violations = len(current_data.get("findings", []))
    errors_count = int(current_data.get("errors_count", 0))
    warnings_count = int(current_data.get("warnings_count", 0))

    score_display = f"**{score:.1f}%**"
    diff_summary_lines: list[str] = []

    if base_data is not None:
        base_score = float(base_data.get("overall_score", 100.0))
        delta = score - base_score
        if abs(delta) < 0.05:
            delta_str = f"0.0% vs {base_ref}"
        elif delta > 0:
            delta_str = f"+{delta:.1f}% vs {base_ref} 📈"
        else:
            delta_str = f"{delta:.1f}% vs {base_ref} 📉"
        score_display = f"**{score:.1f}%** ({delta_str})"

        new_violations, resolved_violations = compare_findings(
            current_data.get("findings", []), base_data.get("findings", [])
        )

        diff_summary_lines.append(f"### 📈 Changes vs `{base_ref}`")
        diff_summary_lines.append(f"- **Score Delta**: `{delta_str}`")
        diff_summary_lines.append(
            f"- **Resolved Violations**: {len(resolved_violations)}"
        )
        diff_summary_lines.append(
            f"- **New Violations**: {len(new_violations)}"
        )

        if new_violations:
            diff_summary_lines.append("\n#### ⚠️ New Violations Introduced")
            diff_summary_lines.append(
                "| Severity | Check | Model / File | Message |"
            )
            diff_summary_lines.append("| :---: | :--- | :--- | :--- |")
            for nv in new_violations[:10]:
                sev = (
                    "🔴 Error"
                    if nv.get("severity") == "error"
                    else "🟡 Warning"
                )
                chk = f"`{nv.get('check', '')}`"
                target = nv.get("model") or nv.get("path") or "-"
                msg = (
                    nv.get("message", "")
                    .replace("\n", " ")
                    .replace("|", "\\|")
                )
                diff_summary_lines.append(
                    f"| {sev} | {chk} | `{target}` | {msg} |"
                )
            if len(new_violations) > 10:
                diff_summary_lines.append(
                    f"*... and {len(new_violations) - 10} more new violations.*"
                )

    lines = [
        PR_COMMENT_MARKER,
        "## 🎯 Transformation Fitness Functions Report\n",
        "| Overall Health Score | Pass/Fail Status | Violations | Errors | Warnings |",
        "| :---: | :---: | :---: | :---: | :---: |",
        f"| {score_display} | {status_badge} | {total_violations} | {errors_count} | {warnings_count} |\n",
        f"> **Threshold**: Minimum score: `{fail_under:.1f}%` · Severity threshold: `{fail_level}`\n",
    ]

    if diff_summary_lines:
        lines.extend(diff_summary_lines)
        lines.append("")

    category_scores = current_data.get("category_scores", {})
    if category_scores:
        cat_lines = [
            "### 📊 Health Score by Category",
            "| Category | Score |",
            "| :--- | :---: |",
        ]
        has_categories = False
        for cat, cat_score in category_scores.items():
            if cat_score is not None:
                has_categories = True
                cat_lines.append(f"| {cat} | {cat_score:.1f}% |")
        if has_categories:
            lines.extend(cat_lines)
            lines.append("")

    findings = current_data.get("findings", [])
    if not findings:
        lines.append("### 🔍 Violations")
        lines.append(
            "✅ **All architectural fitness functions and linter checks passed without any violations!**\n"
        )
    else:
        open_tag = " open" if len(findings) <= 15 else ""
        lines.append(f"### 🔍 Violations Detail ({len(findings)})")
        lines.append(f"<details{open_tag}>")
        lines.append(
            f"<summary><b>Click to expand {len(findings)} violation(s)</b></summary>\n"
        )
        lines.append("| Severity | Check | Model / File | Message |")
        lines.append("| :---: | :--- | :--- | :--- |")
        for f in findings[:50]:
            sev = "🔴 Error" if f.get("severity") == "error" else "🟡 Warning"
            chk = f"`{f.get('check', '')}`"
            target = f.get("model") or f.get("path") or "-"
            msg = f.get("message", "").replace("\n", " ").replace("|", "\\|")
            lines.append(f"| {sev} | {chk} | `{target}` | {msg} |")
        if len(findings) > 50:
            lines.append(
                f"\n*... and {len(findings) - 50} more violations truncated.*"
            )
        lines.append("\n</details>\n")

    lines.append("---")
    lines.append(
        "*Generated by [TFF (Transformation Fitness Functions)](https://github.com/tjirab/tff)*"
    )

    return "\n".join(lines)


def post_or_update_pr_comment(
    token: str,
    repo: str,
    pr_number: int,
    body: str,
    comment_marker: str = PR_COMMENT_MARKER,
) -> int | None:
    """Create or update a GitHub Pull Request comment using the GitHub REST API."""
    if not token:
        print(
            "Warning: GITHUB_TOKEN not provided. Skipping PR comment.",
            file=sys.stderr,
        )
        return None

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "tff-action",
        "Content-Type": "application/json",
    }

    base_url = f"https://api.github.com/repos/{repo}/issues"
    list_url = f"{base_url}/{pr_number}/comments?per_page=100"

    existing_comment_id: int | None = None
    try:
        req = urllib.request.Request(list_url, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=15) as resp:
            comments = json.loads(resp.read().decode("utf-8"))
            for c in comments:
                if comment_marker in c.get("body", ""):
                    existing_comment_id = c.get("id")
                    break
    except urllib.error.HTTPError as e:
        print(
            f"::warning::Failed to query PR comments (HTTP {e.code}: {e.reason}). "
            "Ensure the workflow has 'permissions: pull-requests: write'.",
            file=sys.stderr,
        )
        return None
    except Exception as e:
        print(
            f"::warning::Error checking existing PR comments: {e}",
            file=sys.stderr,
        )
        return None

    payload = json.dumps({"body": body}).encode("utf-8")

    try:
        if existing_comment_id is not None:
            patch_url = f"{base_url}/comments/{existing_comment_id}"
            req = urllib.request.Request(
                patch_url, data=payload, headers=headers, method="PATCH"
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                comment_id = result.get("id", existing_comment_id)
                print(f"Updated existing PR comment #{comment_id}")
                return comment_id
        else:
            post_url = f"{base_url}/{pr_number}/comments"
            req = urllib.request.Request(
                post_url, data=payload, headers=headers, method="POST"
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                comment_id = result.get("id")
                print(f"Created new PR comment #{comment_id}")
                return comment_id
    except urllib.error.HTTPError as e:
        print(
            f"::warning::Failed to post PR comment (HTTP {e.code}: {e.reason}). "
            "Ensure the workflow has 'permissions: pull-requests: write'.",
            file=sys.stderr,
        )
        return None
    except Exception as e:
        print(f"::warning::Error posting PR comment: {e}", file=sys.stderr)
        return None


def detect_pr_context() -> tuple[str | None, int | None]:
    """Detect GitHub repository name and PR number from GitHub Actions environment."""
    repo = os.environ.get("GITHUB_REPOSITORY")
    pr_number: int | None = None

    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if event_path and Path(event_path).is_file():
        try:
            with open(event_path, "r", encoding="utf-8") as f:
                event = json.load(f)
            if "pull_request" in event and "number" in event["pull_request"]:
                pr_number = int(event["pull_request"]["number"])
            if (
                not repo
                and "repository" in event
                and "full_name" in event["repository"]
            ):
                repo = str(event["repository"]["full_name"])
        except Exception as e:
            logger.debug("Failed to read GITHUB_EVENT_PATH: %s", e)

    if pr_number is None:
        ref = os.environ.get("GITHUB_REF", "")
        if ref.startswith("refs/pull/") and "/merge" in ref:
            try:
                pr_number = int(ref.split("/")[2])
            except (IndexError, ValueError):
                pass

    return repo, pr_number


def write_github_output(key: str, val: Any) -> None:
    """Write an output key-value pair to GITHUB_OUTPUT if present."""
    output_file = os.environ.get("GITHUB_OUTPUT")
    if output_file:
        try:
            with open(output_file, "a", encoding="utf-8") as f:
                f.write(f"{key}={val}\n")
        except Exception as e:
            logger.debug("Failed to write to GITHUB_OUTPUT: %s", e)


def write_github_step_summary(content: str) -> None:
    """Append markdown content to GITHUB_STEP_SUMMARY if present."""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        try:
            with open(summary_file, "a", encoding="utf-8") as f:
                f.write(content + "\n")
        except Exception as e:
            logger.debug("Failed to write to GITHUB_STEP_SUMMARY: %s", e)


def execute_action(args: argparse.Namespace) -> int:
    """Execute TFF GitHub Action pipeline."""
    project_root = Path(args.project).resolve()
    checks = None
    if getattr(args, "checks", None):
        checks = [c.strip() for c in args.checks.split(",") if c.strip()]

    # 1. Evaluate current project
    try:
        current_data = evaluate_project(
            project_root=project_root,
            provider=args.provider,
            config_path=args.config,
            checks=checks,
            dialect=getattr(args, "dialect", None),
            manifest=getattr(args, "manifest", None),
        )
    except Exception as e:
        print(
            f"Error evaluating project fitness functions: {e}",
            file=sys.stderr,
        )
        return 1

    # 2. Emit GitHub Actions annotations
    if getattr(args, "annotations", True):
        raw_findings = current_data.get("raw_findings", [])
        if raw_findings:
            emit_github_annotations(
                raw_findings, project_root=project_root, stream=sys.stdout
            )

    # 3. Base branch diff calculation if requested
    base_data: dict[str, Any] | None = None
    base_ref = getattr(args, "base_ref", None) or os.environ.get(
        "GITHUB_BASE_REF"
    )
    if getattr(args, "diff_against_base", True) and base_ref:
        base_data = fetch_base_scores(
            project_dir=project_root,
            base_ref=base_ref,
            provider=args.provider,
            config_path=args.config,
            checks=checks,
        )

    # 4. Generate PR Comment Markdown
    md_report = generate_pr_comment_markdown(
        current_data=current_data,
        base_data=base_data,
        fail_under=args.fail_under,
        fail_level=args.fail_level,
        base_ref=base_ref or "main",
    )

    # 5. Output to terminal / console
    if getattr(args, "json", False):
        out_json = {
            "current": {
                k: v
                for k, v in current_data.items()
                if k not in ("raw_findings", "scores", "config")
            },
            "base": (
                {
                    k: v
                    for k, v in base_data.items()
                    if k not in ("raw_findings", "scores", "config")
                }
                if base_data
                else None
            ),
            "passed": evaluate_pass_fail(
                current_data,
                fail_under=args.fail_under,
                fail_level=args.fail_level,
            ),
        }
        print(json.dumps(out_json, indent=2))
    else:
        render_health_report(
            current_data["scores"],
            current_data["config"],
            current_data["provider"],
        )

    # 6. Write GitHub Step Summary
    write_github_step_summary(md_report)

    # 7. Post or update PR Comment if requested
    comment_id: int | None = None
    should_comment = parse_bool(getattr(args, "comment_pr", False))
    if should_comment:
        repo = getattr(args, "repo", None)
        pr_number = getattr(args, "pr_number", None)
        if not repo or not pr_number:
            detected_repo, detected_pr = detect_pr_context()
            repo = repo or detected_repo
            pr_number = pr_number or detected_pr

        token = getattr(args, "github_token", None) or os.environ.get(
            "GITHUB_TOKEN"
        )
        if repo and pr_number:
            comment_id = post_or_update_pr_comment(
                token=token or "",
                repo=repo,
                pr_number=pr_number,
                body=md_report,
            )
        else:
            print(
                "Notice: comment-pr is enabled, but could not detect pull request context (repository and PR number). Skipping PR comment.",
                file=sys.stderr,
            )

    # 8. Set GitHub Outputs
    passed = evaluate_pass_fail(
        current_data,
        fail_under=args.fail_under,
        fail_level=args.fail_level,
    )
    overall_score = float(current_data.get("overall_score", 100.0))
    total_violations = len(current_data.get("findings", []))
    errors_count = int(current_data.get("errors_count", 0))
    warnings_count = int(current_data.get("warnings_count", 0))

    write_github_output("health-score", f"{overall_score:.1f}")
    write_github_output("violations-count", total_violations)
    write_github_output("errors-count", errors_count)
    write_github_output("warnings-count", warnings_count)
    write_github_output("passed", "true" if passed else "false")
    write_github_output(
        "comment-id", str(comment_id) if comment_id is not None else ""
    )

    if not passed:
        if args.fail_under > 0.0 and overall_score < args.fail_under:
            print(
                f"Error: Project health score {overall_score:.1f}% is below threshold {args.fail_under:.1f}%",
                file=sys.stderr,
            )
        if (
            args.fail_level.lower() == "warning"
            and (errors_count > 0 or warnings_count > 0)
        ) or (args.fail_level.lower() == "error" and errors_count > 0):
            print(
                f"Error: Fitness check violations exist ({errors_count} errors, {warnings_count} warnings) matching fail-level '{args.fail_level}'",
                file=sys.stderr,
            )
        return 1

    return 0


if __name__ == "__main__":  # pragma: no cover
    from tff.core.cli import main

    sys.exit(main(["action"] + sys.argv[1:]))
