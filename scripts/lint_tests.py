#!/usr/bin/env python3
"""Static AST linter enforcing test architecture standards and preventing test bloat."""

from __future__ import annotations

import argparse
import ast
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
from typing import Sequence


DOMAIN_FACTORIES: dict[str, str] = {
    "ModelRepresentation": "Use '_make_model' factory (from conftest) instead of direct 'ModelRepresentation' instantiation.",
    "LintFinding": "Use '_make_finding' factory (from conftest) instead of direct 'LintFinding' instantiation.",
}

# Domain rule/check test files where presentation coupling is strictly prohibited
DOMAIN_RULE_TEST_PATTERNS: tuple[str, ...] = (
    "test_rules_",
    "test_ban_",
    "test_mart_naming",
    "test_column_rules",
    "test_connascence_",
    "test_schema_contracts",
    "test_duplicate_ctes",
    "test_materialization_depth",
    "test_sql_complexity",
    "test_classification_macros",
    "test_no_positional_group_by_or_order_by",
    "test_environment_agnostic_references",
    "test_custom_exclusions",
    "test_layer_filtering",
    "test_join_type_parity",
)


@dataclass(frozen=True)
class LintViolation:
    path: Path
    line: int
    col: int
    code: str
    message: str
    severity: str = "error"

    def format(self) -> str:
        return f"{self.path}:{self.line}:{self.col}: [{self.code}] ({self.severity}) {self.message}"


def _is_domain_rule_test_file(path: Path) -> bool:
    stem = path.stem.lower()
    return any(p in stem for p in DOMAIN_RULE_TEST_PATTERNS)


def check_test_file(path: Path, allowed_lines: set[int] | None = None) -> list[LintViolation]:
    """Inspect a Python test file for test architecture and anti-bloat violations."""
    if path.name == "conftest.py":
        return []

    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(path))
    except Exception as exc:
        return [
            LintViolation(
                path=path,
                line=1,
                col=1,
                code="TB000",
                message=f"Failed to parse AST: {exc}",
                severity="error",
            )
        ]

    violations: list[LintViolation] = []
    is_domain_rule_test = _is_domain_rule_test_file(path)

    # 1. AST Traversal for factory bypass and presentation coupling
    for node in ast.walk(tree):
        if not hasattr(node, "lineno"):
            continue

        lineno = node.lineno
        col_offset = getattr(node, "col_offset", 0) + 1

        if allowed_lines is not None and lineno not in allowed_lines:
            continue

        # Check TB001: Direct ModelRepresentation or LintFinding instantiation
        if isinstance(node, ast.Call):
            func_name = None
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                func_name = node.func.attr

            if func_name in DOMAIN_FACTORIES:
                violations.append(
                    LintViolation(
                        path=path,
                        line=lineno,
                        col=col_offset,
                        code="TB001",
                        message=DOMAIN_FACTORIES[func_name],
                        severity="error",
                    )
                )

            # Check TB002: Presentation coupling in domain rule/check tests
            if is_domain_rule_test:
                coupling_reason = None
                if isinstance(node.func, ast.Attribute) and node.func.attr in ("export_text", "export_html"):
                    coupling_reason = f"calling '.{node.func.attr}()'"
                elif (
                    (isinstance(node.func, ast.Name) and node.func.id == "Console")
                    or (isinstance(node.func, ast.Attribute) and node.func.attr == "Console")
                ):
                    for kw in node.keywords:
                        if kw.arg == "record" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                            coupling_reason = "instantiating 'Console(record=True)'"
                            break

                if coupling_reason:
                    violations.append(
                        LintViolation(
                            path=path,
                            line=lineno,
                            col=col_offset,
                            code="TB002",
                            message=(
                                f"Presentation coupling detected ({coupling_reason}). "
                                "Domain rules and checks must be tested via pure data transformations, "
                                "not terminal string scraping."
                            ),
                            severity="error",
                        )
                    )

    # 2. Check TB003: Repetitive test function clusters that should be parametrized
    func_targets: dict[str, list[ast.FunctionDef]] = defaultdict(list)
    for top_node in tree.body:
        if isinstance(top_node, ast.FunctionDef) and top_node.name.startswith("test_"):
            # Check if function is simple (e.g. <= 4 statements) and calls a single helper
            if len(top_node.body) <= 4:
                target_calls = [
                    n.func.id
                    for n in ast.walk(top_node)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and not n.func.id.startswith("assert")
                ]
                if len(target_calls) == 1:
                    target_name = target_calls[0]
                    # Exclude generic fixtures or standard functions
                    if target_name not in ("len", "set", "dict", "list", "print", "str", "int"):
                        func_targets[target_name].append(top_node)

    for target_name, funcs in func_targets.items():
        if len(funcs) >= 4:
            first_func = funcs[0]
            if allowed_lines is None or any(f.lineno in allowed_lines for f in funcs):
                names_summary = ", ".join(f.name for f in funcs[:3]) + f", ... ({len(funcs)} functions)"
                violations.append(
                    LintViolation(
                        path=path,
                        line=first_func.lineno,
                        col=first_func.col_offset + 1,
                        code="TB003",
                        message=(
                            f"Repetitive test functions detected targeting '{target_name}' ({names_summary}). "
                            "Consider consolidating into a '@pytest.mark.parametrize' matrix."
                        ),
                        severity="warning",
                    )
                )

    return violations


def get_diff_modified_files_and_lines(
    repo_root: Path, compare_branch: str = "origin/main"
) -> dict[Path, set[int] | None]:
    """Retrieve mapping of modified/new test file paths to their added/modified line numbers from git."""
    results: dict[Path, set[int] | None] = {}

    # 1. Check git diff against compare_branch
    try:
        cmd = ["git", "diff", "-U0", compare_branch]
        proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return results

    current_file: Path | None = None
    hunk_regex = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            rel_path = line[6:].strip()
            if "tests" in Path(rel_path).parts and rel_path.endswith(".py"):
                current_file = (repo_root / rel_path).resolve()
                results[current_file] = set()
            else:
                current_file = None
        elif line.startswith("@@ ") and current_file is not None:
            match = hunk_regex.match(line)
            if match:
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) is not None else 1
                lines = results[current_file]
                if lines is not None:
                    for lineno in range(start, start + count):
                        lines.add(lineno)

    # 2. Check untracked test files
    try:
        proc_untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        for rel_line in proc_untracked.stdout.splitlines():
            p = Path(rel_line)
            if "tests" in p.parts and rel_line.endswith(".py"):
                abs_p = (repo_root / p).resolve()
                if abs_p.exists():
                    results[abs_p] = None  # None indicates all lines should be checked
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass

    return results


def find_test_files(repo_root: Path) -> list[Path]:
    """Find all test files in the repository."""
    test_files: list[Path] = []
    for pattern in ("packages/**/tests/**/*.py", "tests/**/*.py"):
        for path in repo_root.glob(pattern):
            if path.is_file() and path.name.endswith(".py"):
                test_files.append(path)
    return sorted(set(test_files))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Static AST linter enforcing test architecture standards and anti-bloat guidelines."
    )
    parser.add_argument(
        "files",
        nargs="*",
        type=Path,
        help="Optional test files to check directly.",
    )
    parser.add_argument(
        "--compare-branch",
        default="origin/main",
        help="Git branch to compare against when checking diff (default: origin/main).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Lint all test files in the repository unconditionally.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat warnings (e.g. TB003) as errors.",
    )

    args = parser.parse_args(argv)
    repo_root = Path.cwd()

    files_to_check: list[tuple[Path, set[int] | None]] = []

    if args.files:
        for f in args.files:
            p = f.resolve()
            files_to_check.append((p, None))
    elif args.all:
        for f in find_test_files(repo_root):
            files_to_check.append((f.resolve(), None))
    else:
        # Default mode: check modified lines from git diff against compare-branch
        diff_files = get_diff_modified_files_and_lines(repo_root, args.compare_branch)
        if diff_files:
            for path, lines in diff_files.items():
                if path.exists():
                    files_to_check.append((path, lines))
        else:
            print(f"PASS — No modified test files in diff against '{args.compare_branch}'.")
            return 0

    all_violations: list[LintViolation] = []

    for path, allowed_lines in files_to_check:
        violations = check_test_file(path, allowed_lines=allowed_lines)
        all_violations.extend(violations)

    errors = [v for v in all_violations if v.severity == "error" or (args.strict and v.severity == "warning")]
    warnings = [v for v in all_violations if v.severity == "warning" and not args.strict]

    for v in all_violations:
        print(v.format())

    if all_violations:
        print()

    if errors:
        print(f"FAIL — {len(errors)} error(s), {len(warnings)} warning(s) found across test files.")
        return 1

    if warnings:
        print(f"PASS (with warnings) — 0 errors, {len(warnings)} warning(s) found.")
        return 0

    print("PASS — All test files comply with test architecture standards.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
