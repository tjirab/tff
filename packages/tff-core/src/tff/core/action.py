"""GitHub Action runner, baseline diff calculator, and PR comment generator for tff."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Sequence
import urllib.error
import urllib.request

from tff.core.adapter import detect_provider, get_adapter, normalize_project_roots
from tff.core.config import load_fitness_config
from tff.core.formatters import emit_github_annotations
from tff.core.health import _get_action_phrase, calculate_health_scores, render_health_report
from tff.core.registry import registry
from tff.core.report import CONNASCENCE_CATEGORIES, LintFinding, _format_connascence_tag
from tff.core.utils.paths import is_finding_in_files

logger = logging.getLogger(__name__)

PR_COMMENT_MARKER = "<!-- tff-pr-comment -->"

AUTOFIXABLE_CHECKS = {
    "filenameequalsmodelname",
    "filename_equals_modelname",
}

REMEDIATION_SNIPPET = (
    "```bash\n"
    "# Remediate autofixable violations locally:\n"
    "tff lint --fix --staged\n"
    "```"
)


def is_autofixable(finding: dict[str, Any] | LintFinding) -> bool:
    """Determine whether a lint finding can be resolved via tff lint --fix."""
    chk = str(
        finding.check
        if isinstance(finding, LintFinding)
        else finding.get("check") or ""
    )
    rule_def = registry.get(chk)
    if rule_def is not None and rule_def.is_fixable:
        return True
    norm = chk.lower().replace("-", "").replace("_", "").replace(" ", "")
    return norm in {
        c.lower().replace("-", "").replace("_", "").replace(" ", "")
        for c in AUTOFIXABLE_CHECKS
    }



def _format_check_cell(check_name: str) -> str:
    """Format check name with documentation hyperlink if available."""
    if not check_name:
        return "`unknown`"
    url = registry.get_docs_url(check_name)
    if url:
        return f"[`{check_name}`]({url})"
    return f"`{check_name}`"


def _make_markdown_progress_bar(score: float, width: int = 10) -> str:
    """Generate a clean Unicode block progress bar for Markdown tables."""
    filled = int(round(score / 100 * width))
    return "█" * filled + "░" * (width - filled)


def _get_coupling_tag(check: str) -> str:
    """Resolve short coupling tag for a check name."""
    cat = CONNASCENCE_CATEGORIES.get(check, "")
    if cat:
        return _format_connascence_tag(cat)
    return "quality"


def _format_finding_row(f: dict[str, Any] | LintFinding) -> str:
    """Format a single finding row for Markdown tables with status tokens and autofix badges."""
    if isinstance(f, LintFinding):
        sev_raw = f.severity
        chk_raw = f.check
        target = f.model or (str(f.path) if f.path else "-")
        msg_raw = f.message
    else:
        sev_raw = f.get("severity")
        chk_raw = f.get("check", "")
        target = f.get("model") or f.get("path") or "-"
        msg_raw = f.get("message", "")

    sev = "`ERR`" if sev_raw == "error" else "`WRN`"
    sig = "!" if sev_raw == "error" else "*"
    chk = _format_check_cell(chk_raw)
    coup = f"`{_get_coupling_tag(chk_raw)}`"
    msg = msg_raw.replace("\n", " ").replace("|", "\\|")
    autofix_badge = " `[Autofixable]`" if is_autofixable(f) else ""
    return f"| {sev} | `{target}` | {chk} | {coup} | {sig} {msg}{autofix_badge} |"



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
                "col": f.col,
                "end_line": f.end_line,
                "end_col": f.end_col,
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


_SANITIZED_GIT_ENV_VARS = frozenset({
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_OBJECT_DIRECTORY",
})


def _git_clean_env() -> dict[str, str]:
    """Return a copy of os.environ with git override variables removed."""
    return {
        k: v
        for k, v in os.environ.items()
        if k not in _SANITIZED_GIT_ENV_VARS
    }


def get_modified_files(
    repo_root: Path,
    base_ref: str = "main",
) -> set[str]:
    """Get list of modified/added files compared to base_ref."""
    clean_env = _git_clean_env()
    try:
        cmd = ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"]
        res = subprocess.run(
            cmd, cwd=str(repo_root), capture_output=True, text=True, env=clean_env
        )
        if res.returncode != 0:
            cmd = ["git", "diff", "--name-only", f"{base_ref}...HEAD"]
            res = subprocess.run(
                cmd, cwd=str(repo_root), capture_output=True, text=True, env=clean_env
            )
        if res.returncode != 0:
            cmd = ["git", "diff", "--name-only", "HEAD~1"]
            res = subprocess.run(
                cmd, cwd=str(repo_root), capture_output=True, text=True, env=clean_env
            )

        if res.returncode == 0:
            return {
                line.strip().replace("\\", "/")
                for line in res.stdout.splitlines()
                if line.strip()
            }
    except Exception as e:
        logger.debug("Failed to get modified files: %s", e)
    return set()


def evaluate_project(
    project_root: Path | Sequence[Path],
    provider: str = "auto",
    config_path: str = "fitness_functions.yaml",
    checks: list[str] | None = None,
    dialect: str | None = None,
    manifest: Path | None = None,
    workers: int | None = None,
    chunk_size: int | None = None,
    scoped_models: set[str] | None = None,
) -> dict[str, Any]:
    """Run tff health evaluation on the specified project directory (or directories)."""
    roots = normalize_project_roots(project_root)
    primary_root = roots[0]
    target_root: Path | list[Path] = roots if len(roots) > 1 else primary_root

    if provider == "auto":
        cfg_path = config_path if config_path != "fitness_functions.yaml" else None
        provider = detect_provider(roots, config_path=cfg_path)

    adapter = get_adapter(provider)
    config = load_fitness_config(roots, config_path=config_path)
    if workers is not None:
        config.workers = workers
    if chunk_size is not None:
        config.chunk_size = chunk_size

    kwargs: dict[str, Any] = {
        "project_root": target_root,
        "config": config,
        "checks": checks,
        "dialect": dialect,
        "manifest_path": manifest,
    }
    if scoped_models is not None:
        kwargs["scoped_models"] = scoped_models
    if chunk_size is not None:
        import inspect

        sig = inspect.signature(adapter.run_checks)
        if "chunk_size" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ):
            kwargs["chunk_size"] = chunk_size

    findings, models_checked, executed_checks = adapter.run_checks(**kwargs)

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

    res: dict[str, Any] = {
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
    if len(roots) > 1:
        res["project_roots"] = [str(r) for r in roots]
    return res


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
    project_dir: Path | Sequence[Path],
    base_ref: str,
    provider: str = "auto",
    config_path: str = "fitness_functions.yaml",
    checks: list[str] | None = None,
    dialect: str | None = None,
    manifest: Path | None = None,
    workers: int | None = None,
) -> dict[str, Any] | None:
    """Attempt to checkout base_ref in a temp git worktree and calculate baseline health score."""
    roots = normalize_project_roots(project_dir)
    primary_root = roots[0]
    clean_env = _git_clean_env()
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(primary_root),
            capture_output=True,
            text=True,
            check=True,
            env=clean_env,
        )
        repo_root = Path(res.stdout.strip()).resolve()
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
            env=clean_env,
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
            worktree_cmd,
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            env=clean_env,
        )
        if res.returncode != 0:
            worktree_cmd[-1] = base_ref
            res = subprocess.run(
                worktree_cmd,
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                env=clean_env,
            )
            if res.returncode != 0:
                logger.debug("git worktree add failed: %s", res.stderr)
                return None

        base_project_dirs: list[Path] = []
        for r in roots:
            try:
                rel = r.relative_to(repo_root)
                base_p = Path(temp_dir) / rel
                if base_p.exists():
                    base_project_dirs.append(base_p)
            except ValueError:
                pass

        if not base_project_dirs:
            logger.debug(
                "Base project path(s) do not exist in base ref: %s",
                roots,
            )
            return None

        target_base_root: Path | list[Path] = (
            base_project_dirs if len(roots) > 1 else base_project_dirs[0]
        )

        resolved_manifest = manifest.resolve() if manifest is not None else None
        return evaluate_project(
            project_root=target_base_root,
            provider=provider,
            config_path=config_path,
            checks=checks,
            dialect=dialect,
            manifest=resolved_manifest,
            workers=workers,
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
            env=clean_env,
        )
        if Path(temp_dir).exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def generate_pr_comment_markdown(
    current_data: dict[str, Any],
    base_data: dict[str, Any] | None = None,
    fail_under: float = 0.0,
    fail_level: str = "error",
    base_ref: str = "main",
    only_changed: bool = False,
    modified_files_count: int = 0,
    ignored_violations_count: int = 0,
    modified_files: set[str] | None = None,
) -> str:
    """Generate the GitHub PR markdown comment summarizing health score and violations."""
    score = float(current_data.get("overall_score", 100.0))
    passed = evaluate_pass_fail(
        current_data, fail_under=fail_under, fail_level=fail_level
    )
    status_badge = "**PASSED**" if passed else "**FAILED**"

    all_findings = current_data.get("findings", [])
    total_violations = len(all_findings)
    errors_count = int(current_data.get("errors_count", 0))
    warnings_count = int(current_data.get("warnings_count", 0))

    new_violations: list[dict[str, Any]] = []
    resolved_violations: list[dict[str, Any]] = []
    delta_str: str | None = None
    delta_compact_str: str = ""

    if base_data is not None:
        base_score = float(base_data.get("overall_score", 100.0))
        delta = score - base_score
        if abs(delta) < 0.05:
            delta_str = f"0.0% vs {base_ref}"
            delta_compact_str = " (0.0%)"
        elif delta > 0:
            delta_str = f"+{delta:.1f}% vs {base_ref}"
            delta_compact_str = f" (+{delta:.1f}%)"
        else:
            delta_str = f"{delta:.1f}% vs {base_ref}"
            delta_compact_str = f" ({delta:.1f}%)"

        new_violations, resolved_violations = compare_findings(
            all_findings, base_data.get("findings", [])
        )

    # Classify touched vs untouched models
    touched_files: set[str] = set()
    touched_stems: set[str] = set()
    if modified_files:
        for mf in modified_files:
            p = Path(mf)
            touched_files.add(p.as_posix())
            touched_stems.add(p.stem)
    for nv in new_violations:
        if nv.get("model"):
            touched_stems.add(str(nv["model"]))
        if nv.get("path"):
            p = Path(nv["path"])
            touched_files.add(p.as_posix())
            touched_stems.add(p.stem)

    new_fps = {get_finding_fingerprint(nv) for nv in new_violations}
    pre_existing = [
        f for f in all_findings if get_finding_fingerprint(f) not in new_fps
    ]

    def _is_untouched(f: dict[str, Any] | LintFinding) -> bool:
        if not touched_files and not touched_stems:
            return base_data is not None
        m = f.model if isinstance(f, LintFinding) else f.get("model")
        if m and m in touched_stems:
            return False
        p = f.path if isinstance(f, LintFinding) else f.get("path")
        if p and Path(p).stem in touched_stems:
            return False
        return True

    untouched_pre_existing: list[dict[str, Any]] = []
    touched_findings: list[dict[str, Any]] = []

    if base_data is not None or modified_files:
        for f in pre_existing:
            if _is_untouched(f):
                untouched_pre_existing.append(f)
        touched_findings = [
            f for f in all_findings if f not in untouched_pre_existing
        ]
    else:
        touched_findings = list(all_findings)

    # 4. Compact Green Pass Card: when all checks pass, no new violations are introduced,
    # and no touched models have violations (or if base_data is unavailable, when there are zero violations).
    if (
        passed
        and not new_violations
        and not touched_findings
        and (base_data is not None or not all_findings)
    ):
        score_val = f"{score:.1f}%"
        card_line = f"**tff Quality Gate Passed** — Health Score: {score_val}{delta_compact_str}"
        lines = [
            PR_COMMENT_MARKER,
            card_line,
        ]

        if untouched_pre_existing:
            lines.append("")
            lines.append("<details>")
            lines.append(
                f"<summary>View {len(untouched_pre_existing)} pre-existing violations across untouched models</summary>\n"
            )
            lines.append("| STATUS | LOCATION | RULE | COUPLING | DETAILS |")
            lines.append("| :---: | :--- | :--- | :--- | :--- |")
            for f in untouched_pre_existing[:50]:
                lines.append(_format_finding_row(f))
            if len(untouched_pre_existing) > 50:
                lines.append(
                    f"\n*... and {len(untouched_pre_existing) - 50} more pre-existing violations truncated.*"
                )
            lines.append("\n</details>")

            if any(is_autofixable(f) for f in untouched_pre_existing):
                lines.append("")
                lines.append(REMEDIATION_SNIPPET)

        lines.append("")
        lines.append("---")
        lines.append(
            "■ ▲ ● *Generated by [tff (Transformation Fitness Functions)](https://github.com/tjirab/tff)*"
        )
        return "\n".join(lines)

    score_display = (
        f"**{score:.1f}%** ({delta_str})" if delta_str else f"**{score:.1f}%**"
    )

    diff_summary_lines: list[str] = []
    if base_data is not None and delta_str is not None:
        diff_summary_lines.append(f"### Changes vs `{base_ref}`")
        diff_summary_lines.append(f"- **Score Delta**: `{delta_str}`")
        diff_summary_lines.append(
            f"- **Resolved Violations**: {len(resolved_violations)}"
        )
        diff_summary_lines.append(
            f"- **New Violations**: {len(new_violations)}"
        )

    if only_changed:
        threshold_line = (
            f"> **Mode**: Gating `{modified_files_count}` modified file(s) in PR · "
            f"Minimum score: `{fail_under:.1f}%` · Severity threshold: `{fail_level}`\n"
        )
        if ignored_violations_count > 0:
            threshold_line += (
                f"> *{ignored_violations_count} pre-existing violation(s) "
                f"in unmodified files were excluded due to `only-changed: true`.*\n"
            )
    else:
        threshold_line = f"> **Threshold**: Minimum score: `{fail_under:.1f}%` · Severity threshold: `{fail_level}`\n"

    lines = [
        PR_COMMENT_MARKER,
        "## ■ ▲ ● TFF ARCHITECTURE AUDIT\n",
    ]

    has_autofix = any(is_autofixable(f) for f in all_findings)

    # 1. Diff-First Triage View: place new violations at the very top under > [!CAUTION]
    if new_violations:
        lines.append("> [!CAUTION]")
        lines.append("> ### New Violations Introduced in This PR\n>")
        lines.append("> | STATUS | LOCATION | RULE | COUPLING | DETAILS |")
        lines.append("> | :---: | :--- | :--- | :--- | :--- |")
        sorted_new_violations = sorted(
            new_violations,
            key=lambda nv: (
                str(nv.get("model") or nv.get("path") or "").lower(),
                0 if nv.get("severity") == "error" else 1,
                str(nv.get("check") or "").lower(),
            ),
        )
        for nv in sorted_new_violations[:25]:
            lines.append(f"> {_format_finding_row(nv)}")
        if len(sorted_new_violations) > 25:
            lines.append(
                f"> \n> *... and {len(sorted_new_violations) - 25} more new violations.*"
            )
        lines.append("")

        if any(is_autofixable(nv) for nv in new_violations):
            lines.append(REMEDIATION_SNIPPET)
            lines.append("")

    lines.extend([
        "| OVERALL HEALTH | STATUS | DEFECTS | ERRORS | WARNINGS |",
        "| :---: | :---: | :---: | :---: | :---: |",
        f"| {score_display} | {status_badge} | {total_violations} | {errors_count} | {warnings_count} |\n",
        threshold_line,
    ])

    if diff_summary_lines:
        lines.extend(diff_summary_lines)
        lines.append("")

    category_scores = current_data.get("category_scores", {})
    if category_scores:
        cat_lines = [
            "### DIMENSION DISTRIBUTION",
            "| DIMENSION | SCORE | DISTRIBUTION (0-100) |",
            "| :--- | :---: | :--- |",
        ]
        has_categories = False
        for cat, cat_score in category_scores.items():
            if cat_score is not None:
                has_categories = True
                bar_str = _make_markdown_progress_bar(cat_score, width=10)
                cat_lines.append(f"| {cat} | {cat_score:.1f}% | `{bar_str}` |")
        if has_categories:
            lines.extend(cat_lines)
            lines.append("")

    # Violations detail (touched findings or all findings if not diff-mode)
    detail_findings = (
        touched_findings
        if (base_data is not None or modified_files)
        else all_findings
    )
    if not detail_findings and not untouched_pre_existing:
        lines.append("### AUDIT LEDGER")
        lines.append(
            "All architectural fitness functions and linter checks passed without any violations!\n"
        )
    elif detail_findings:
        open_tag = " open" if len(detail_findings) <= 15 else ""
        lines.append(f"### Violations Detail ({len(detail_findings)})")
        lines.append(f"<details{open_tag}>")
        lines.append(
            f"<summary><b>Click to expand {len(detail_findings)} violation(s)</b></summary>\n"
        )
        lines.append("| STATUS | LOCATION | RULE | COUPLING | DETAILS |")
        lines.append("| :---: | :--- | :--- | :--- | :--- |")
        for f in detail_findings[:50]:
            lines.append(_format_finding_row(f))
        if len(detail_findings) > 50:
            lines.append(
                f"\n*... and {len(detail_findings) - 50} more violations truncated.*"
            )
        lines.append("\n</details>\n")

    # 2. Collapsible Baseline Debt: pre-existing violations on untouched models
    if untouched_pre_existing:
        lines.append("<details>")
        lines.append(
            f"<summary>View {len(untouched_pre_existing)} pre-existing violations across untouched models</summary>\n"
        )
        lines.append("| STATUS | LOCATION | RULE | COUPLING | DETAILS |")
        lines.append("| :---: | :--- | :--- | :--- | :--- |")
        for f in untouched_pre_existing[:50]:
            lines.append(_format_finding_row(f))
        if len(untouched_pre_existing) > 50:
            lines.append(
                f"\n*... and {len(untouched_pre_existing) - 50} more pre-existing violations truncated.*"
            )
        lines.append("\n</details>\n")

    if has_autofix and not (
        new_violations and any(is_autofixable(nv) for nv in new_violations)
    ):
        lines.append(REMEDIATION_SNIPPET)
        lines.append("")

    # Action footer
    if all_findings:
        check_counts: dict[str, int] = defaultdict(int)
        for f in all_findings:
            chk = f.check if isinstance(f, LintFinding) else f.get("check", "")
            check_counts[chk] += 1
        top_check, top_count = sorted(
            check_counts.items(), key=lambda x: x[1], reverse=True
        )[0]
        action_verb = _get_action_phrase(top_check, top_count)
        target = fail_under if fail_under > 0 else 80.0
        if score < target:
            lines.append(
                f"> **ACTION**: {action_verb} to raise score above {target:.1f}%.\n"
            )
        else:
            lines.append(
                f"> **ACTION**: {action_verb} to improve project fitness.\n"
            )
    else:
        lines.append(
            "> **ACTION**: All fitness functions satisfied. Fitness score is optimal.\n"
        )

    lines.append("---")
    lines.append(
        "■ ▲ ● *Generated by [tff (Transformation Fitness Functions)](https://github.com/tjirab/tff)*"
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
    """Execute tff GitHub Action pipeline."""
    projects_val = getattr(args, "projects", None)
    project_val = getattr(args, "project", None)
    if isinstance(projects_val, (list, tuple)) and projects_val:
        project_roots = [Path(p).resolve() for p in projects_val]
    elif isinstance(project_val, (list, tuple)) and project_val:
        project_roots = [Path(p).resolve() for p in project_val]
    elif isinstance(project_val, (str, Path)):
        project_roots = [Path(project_val).resolve()]
    else:
        project_roots = [Path.cwd()]
    primary_root = project_roots[0]
    target_project_root: Path | list[Path] = (
        project_roots if len(project_roots) > 1 else primary_root
    )

    checks = None
    if getattr(args, "checks", None):
        checks = [c.strip() for c in args.checks.split(",") if c.strip()]

    only_changed = parse_bool(getattr(args, "only_changed", False))
    diff_base = getattr(args, "base_ref", None) or os.environ.get("GITHUB_BASE_REF") or "main"
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(primary_root),
            capture_output=True,
            text=True,
            check=True,
            env=_git_clean_env(),
        )
        repo_root = Path(res.stdout.strip()).resolve()
    except Exception:
        repo_root = primary_root

    modified_files = get_modified_files(repo_root, base_ref=diff_base)
    modified_files_count = len(modified_files)
    scoped_models: set[str] | None = None

    if only_changed and modified_files:
        from tff.core.git import map_files_to_model_names
        from tff.core.adapter import get_adapter

        try:
            adapter = get_adapter(args.provider if args.provider != "auto" else detect_provider(target_project_root))
            loaded_models = adapter.load_models(target_project_root, dialect=getattr(args, "dialect", None), manifest_path=getattr(args, "manifest", None))
            scoped_models = map_files_to_model_names(
                models=loaded_models,
                files=modified_files,
                project_root=target_project_root,
                repo_root=repo_root,
            )
        except Exception as e:
            logger.debug("Failed to pre-scope models for only-changed: %s", e)

    # 1. Evaluate current project
    try:
        current_data = evaluate_project(
            project_root=target_project_root,
            provider=args.provider,
            config_path=args.config,
            checks=checks,
            dialect=getattr(args, "dialect", None),
            manifest=getattr(args, "manifest", None),
            workers=getattr(args, "workers", None),
            chunk_size=getattr(args, "chunk_size", None),
            scoped_models=scoped_models,
        )
    except Exception as e:
        print(
            f"Error evaluating project fitness functions: {e}",
            file=sys.stderr,
        )
        return 1

    # 2. Filter findings for only-changed files if requested
    ignored_violations_count = 0

    if only_changed:
        all_findings = current_data.get("findings", [])
        all_raw_findings = current_data.get("raw_findings", [])

        filtered_findings = [
            f
            for f in all_findings
            if is_finding_in_files(f, modified_files, target_project_root, repo_root)
        ]
        filtered_raw_findings = [
            f
            for f in all_raw_findings
            if is_finding_in_files(f, modified_files, target_project_root, repo_root)
        ]

        ignored_violations_count = len(all_findings) - len(filtered_findings)
        current_data["findings"] = filtered_findings
        current_data["raw_findings"] = filtered_raw_findings
        current_data["errors_count"] = sum(
            1 for f in filtered_findings if f.get("severity") == "error"
        )
        current_data["warnings_count"] = sum(
            1 for f in filtered_findings if f.get("severity") == "warning"
        )

    # 3. Emit GitHub Actions annotations
    if getattr(args, "annotations", True):
        raw_findings = current_data.get("raw_findings", [])
        if raw_findings:
            emit_github_annotations(
                raw_findings,
                project_root=target_project_root,
                stream=sys.stdout,
                modified_files=modified_files,
            )

    # 4. Base branch diff calculation if requested
    base_data: dict[str, Any] | None = None
    base_ref = getattr(args, "base_ref", None) or os.environ.get(
        "GITHUB_BASE_REF"
    )
    base_manifest = getattr(args, "base_manifest", None)
    if getattr(args, "diff_against_base", True) and base_ref:
        base_data = fetch_base_scores(
            project_dir=target_project_root,
            base_ref=base_ref,
            provider=args.provider,
            config_path=args.config,
            checks=checks,
            dialect=getattr(args, "dialect", None),
            manifest=base_manifest,
            workers=getattr(args, "workers", None),
        )

    # 5. Generate PR Comment Markdown
    md_report = generate_pr_comment_markdown(
        current_data=current_data,
        base_data=base_data,
        fail_under=args.fail_under,
        fail_level=args.fail_level,
        base_ref=base_ref or "main",
        only_changed=only_changed,
        modified_files_count=modified_files_count,
        ignored_violations_count=ignored_violations_count,
        modified_files=modified_files,
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
        if len(project_roots) > 1:
            out_json["project_roots"] = [str(p) for p in project_roots]
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
