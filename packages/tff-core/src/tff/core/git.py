"""Git inspection and model scoping utilities for tff."""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from typing import TYPE_CHECKING

from tff.core.report import normalize_model_name

if TYPE_CHECKING:
    from tff.core.model import ModelRepresentation

logger = logging.getLogger(__name__)


def get_git_root(path: Path | str | None = None) -> Path | None:
    """Return the git repository root for the given path, or None if not inside a git repository."""
    target = Path(path).resolve() if path is not None else Path.cwd().resolve()
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(target),
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(res.stdout.strip()).resolve()
    except Exception:
        return None


def get_staged_files(repo_root: Path) -> set[str]:
    """Get list of files currently staged in git (index vs HEAD)."""
    res = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    if res.returncode == 0:
        return {
            line.strip().replace("\\", "/")
            for line in res.stdout.splitlines()
            if line.strip()
        }
    return set()


def get_changed_files_since(repo_root: Path, ref: str) -> set[str]:
    """Get list of modified/added files compared to a git ref.

    Attempts standard 3-dot diff (merge-base) first, followed by direct 2-dot/ref diff,
    and handles remote origin branches if needed.
    """
    clean_ref = ref.strip()
    if not clean_ref:
        return set()

    diff_targets = [f"{clean_ref}...HEAD", clean_ref]
    if not clean_ref.startswith("origin/"):
        diff_targets.append(f"origin/{clean_ref}...HEAD")

    for diff_target in diff_targets:
        res = subprocess.run(
            ["git", "diff", "--name-only", diff_target],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if res.returncode == 0:
            return {
                line.strip().replace("\\", "/")
                for line in res.stdout.splitlines()
                if line.strip()
            }

    from tff.core.exceptions import TffGitError

    raise TffGitError(
        f"Unknown or invalid git reference: '{clean_ref}'.",
        hint=f"Verify that branch/commit '{clean_ref}' exists in git.",
    )


def map_files_to_model_names(
    models: dict[str, ModelRepresentation],
    files: set[str],
    project_root: Path,
    repo_root: Path,
) -> set[str]:
    """Map a set of repo-relative file paths to model names present in the project.

    Matches by:
    1. Exact or suffix path matching against model.path.
    2. File stem matching (e.g. `dim_customers.sql` -> `dim_customers`).
    3. Normalized model name matching.
    """
    if not files or not models:
        return set()

    norm_files = {f.replace("\\", "/").strip() for f in files if f.strip()}
    file_stems = {Path(f).stem.lower(): f for f in norm_files}

    try:
        rel_project = project_root.resolve().relative_to(repo_root.resolve())
        rel_proj_str = str(rel_project).replace("\\", "/")
        if rel_proj_str == ".":
            rel_proj_str = ""
    except Exception:
        rel_proj_str = ""

    matched_models: set[str] = set()

    for model_name, model in models.items():
        m_name_clean = normalize_model_name(model_name)
        m_path_str = str(model.path or "").replace("\\", "/").strip()
        m_stem = Path(m_path_str).stem.lower() if m_path_str else m_name_clean.lower()

        # 1. Path match against model.path
        if m_path_str:
            full_rel = f"{rel_proj_str}/{m_path_str}".strip("/") if rel_proj_str else m_path_str
            if (
                full_rel in norm_files
                or m_path_str in norm_files
                or any(nf.endswith(f"/{m_path_str}") for nf in norm_files)
            ):
                matched_models.add(model_name)
                continue

        # 2. File stem match against model name or model.path stem
        if m_stem in file_stems or m_name_clean.lower() in file_stems:
            matched_models.add(model_name)

    return matched_models
