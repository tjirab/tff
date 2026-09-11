"""Tests for .pre-commit-hooks.yaml configuration."""

from pathlib import Path
import yaml


_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_pre_commit_hooks_file_exists() -> None:
    manifest_path = _REPO_ROOT / ".pre-commit-hooks.yaml"
    assert manifest_path.is_file(), f".pre-commit-hooks.yaml not found in {_REPO_ROOT}"


def test_pre_commit_hooks_structure() -> None:
    manifest_path = _REPO_ROOT / ".pre-commit-hooks.yaml"
    content = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    assert isinstance(content, list), "Expected list of hook definitions"
    assert len(content) >= 2, "Expected at least 2 hooks (tff-lint and tff-lint-fix)"

    hooks_by_id = {hook["id"]: hook for hook in content}
    assert "tff-lint" in hooks_by_id
    assert "tff-lint-fix" in hooks_by_id

    # Validate tff-lint hook
    tff_lint = hooks_by_id["tff-lint"]
    assert tff_lint["name"] == "TFF Lint"
    assert "Run Transformation Fitness Functions" in tff_lint["description"]
    assert tff_lint["entry"] == "tff lint"
    assert tff_lint["language"] == "python"
    assert tff_lint["types_or"] == ["sql", "yaml", "json"]
    assert tff_lint["pass_filenames"] is False
    assert tff_lint["additional_dependencies"] == ["tff-core"]

    # Validate tff-lint-fix hook
    tff_lint_fix = hooks_by_id["tff-lint-fix"]
    assert tff_lint_fix["name"] == "TFF Auto-Fix"
    assert "Automatically fix" in tff_lint_fix["description"]
    assert tff_lint_fix["entry"] == "tff lint --fix"
    assert tff_lint_fix["language"] == "python"
    assert tff_lint_fix["types_or"] == ["sql", "yaml"]
    assert tff_lint_fix["pass_filenames"] is False
    assert tff_lint_fix["additional_dependencies"] == ["tff-core"]
