"""Tests for the test architecture and anti-bloat static AST linter."""

from __future__ import annotations

from pathlib import Path
import sys

# Ensure repository root is on sys.path so scripts module can be imported
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:  # pragma: no cover
    sys.path.insert(0, str(REPO_ROOT))

from scripts.lint_tests import (  # noqa: E402
    LintViolation,
    check_test_file,
    find_test_files,
    get_diff_modified_files_and_lines,
    main,
)


def test_lint_violation_format() -> None:
    v = LintViolation(
        path=Path("tests/test_demo.py"),
        line=10,
        col=5,
        code="TB001",
        message="Use '_make_model' factory.",
        severity="error",
    )
    assert v.format() == "tests/test_demo.py:10:5: [TB001] (error) Use '_make_model' factory."


def test_conftest_is_exempt(tmp_path: Path) -> None:
    conftest = tmp_path / "conftest.py"
    conftest.write_text(
        "from tff.core.model import ModelRepresentation\n"
        "def _make_model():\n"
        "    return ModelRepresentation(name='test', path='test.sql', dialect='duckdb')\n",
        encoding="utf-8",
    )
    violations = check_test_file(conftest)
    assert violations == []


def test_detects_factory_bypass(tmp_path: Path) -> None:
    test_file = tmp_path / "test_sample.py"
    test_file.write_text(
        "from tff.core.model import ModelRepresentation\n"
        "from tff.core.report import LintFinding\n"
        "def test_foo():\n"
        "    m = ModelRepresentation(name='foo', path='foo.sql', dialect='duckdb')\n"
        "    f = LintFinding(check='banselectstar', severity='error', message='violation')\n",
        encoding="utf-8",
    )
    violations = check_test_file(test_file)
    assert len(violations) == 2
    assert all(v.code == "TB001" for v in violations)
    assert any("ModelRepresentation" in v.message for v in violations)
    assert any("LintFinding" in v.message for v in violations)


def test_detects_presentation_coupling_in_rule_tests(tmp_path: Path) -> None:
    rule_test = tmp_path / "test_ban_select_star.py"
    rule_test.write_text(
        "from rich.console import Console\n"
        "def test_render():\n"
        "    console = Console(record=True)\n"
        "    out = console.export_text()\n"
        "    html = console.export_html()\n",
        encoding="utf-8",
    )
    violations = check_test_file(rule_test)
    assert len(violations) == 3
    assert all(v.code == "TB002" for v in violations)
    assert any("record=True" in v.message for v in violations)
    assert any("export_text" in v.message for v in violations)
    assert any("export_html" in v.message for v in violations)


def test_allows_presentation_testing_in_reporter_tests(tmp_path: Path) -> None:
    report_test = tmp_path / "test_report.py"
    report_test.write_text(
        "from rich.console import Console\n"
        "def test_report():\n"
        "    console = Console(record=True)\n"
        "    out = console.export_text()\n",
        encoding="utf-8",
    )
    violations = check_test_file(report_test)
    assert violations == []


def test_detects_repetitive_function_cluster(tmp_path: Path) -> None:
    test_file = tmp_path / "test_repetitive.py"
    test_file.write_text(
        "def helper(x): return x + 1\n"
        "def test_a(): assert helper(1) == 2\n"
        "def test_b(): assert helper(2) == 3\n"
        "def test_c(): assert helper(3) == 4\n"
        "def test_d(): assert helper(4) == 5\n",
        encoding="utf-8",
    )
    violations = check_test_file(test_file)
    assert any(v.code == "TB003" and v.severity == "warning" for v in violations)


def test_syntax_error_handled_gracefully(tmp_path: Path) -> None:
    bad_syntax = tmp_path / "test_bad.py"
    bad_syntax.write_text("def invalid syntax :::", encoding="utf-8")
    violations = check_test_file(bad_syntax)
    assert len(violations) == 1
    assert violations[0].code == "TB000"


def test_allowed_lines_filtering(tmp_path: Path) -> None:
    test_file = tmp_path / "test_allowed.py"
    test_file.write_text(
        "from tff.core.model import ModelRepresentation\n"
        "def test_old():\n"
        "    m = ModelRepresentation(name='old', path='old.sql', dialect='duckdb')\n"
        "def test_new():\n"
        "    m2 = ModelRepresentation(name='new', path='new.sql', dialect='duckdb')\n",
        encoding="utf-8",
    )
    # Only line 5 is in allowed_lines (simulating diff-only check)
    violations = check_test_file(test_file, allowed_lines={5})
    assert len(violations) == 1
    assert violations[0].line == 5


def test_find_test_files(tmp_path: Path) -> None:
    t1 = tmp_path / "packages" / "pkg1" / "tests" / "test_one.py"
    t1.parent.mkdir(parents=True, exist_ok=True)
    t1.write_text("def test_x(): pass\n", encoding="utf-8")

    files = find_test_files(tmp_path)
    assert len(files) == 1
    assert files[0] == t1


def test_get_diff_modified_files_and_lines(tmp_path: Path) -> None:
    # Running in non-git directory returns empty dict gracefully
    result = get_diff_modified_files_and_lines(tmp_path, compare_branch="origin/main")
    assert isinstance(result, dict)


def test_main_cli_clean_file(tmp_path: Path, capsys) -> None:
    clean_test = tmp_path / "test_clean.py"
    clean_test.write_text("def test_clean(): assert 1 == 1\n", encoding="utf-8")

    exit_code = main([str(clean_test)])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS — All test files comply with test architecture standards." in out


def test_main_cli_failing_file(tmp_path: Path, capsys) -> None:
    bad_test = tmp_path / "test_fail.py"
    bad_test.write_text(
        "from tff.core.model import ModelRepresentation\n"
        "def test_f(): ModelRepresentation(name='x', path='x.sql', dialect='duckdb')\n",
        encoding="utf-8",
    )

    exit_code = main([str(bad_test)])
    assert exit_code == 1
    out = capsys.readouterr().out
    assert "[TB001]" in out
    assert "FAIL — 1 error(s)" in out


def test_main_cli_strict_mode_warnings(tmp_path: Path, capsys) -> None:
    rep_test = tmp_path / "test_rep.py"
    rep_test.write_text(
        "def f(x): return x\n"
        "def test_1(): assert f(1) == 1\n"
        "def test_2(): assert f(2) == 2\n"
        "def test_3(): assert f(3) == 3\n"
        "def test_4(): assert f(4) == 4\n",
        encoding="utf-8",
    )

    # Without strict: exit code 0
    exit_non_strict = main([str(rep_test)])
    assert exit_non_strict == 0
    out_non_strict = capsys.readouterr().out
    assert "PASS (with warnings)" in out_non_strict

    # With strict: exit code 1
    exit_strict = main([str(rep_test), "--strict"])
    assert exit_strict == 1
    out_strict = capsys.readouterr().out
    assert "FAIL — 1 error(s)" in out_strict


def test_main_cli_diff_mode_clean(monkeypatch, capsys) -> None:
    # When diff returns no modified files
    monkeypatch.setattr("scripts.lint_tests.get_diff_modified_files_and_lines", lambda *args, **kwargs: {})
    exit_code = main([])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS — No modified test files in diff" in out


def test_main_cli_all_mode(tmp_path: Path, monkeypatch, capsys) -> None:
    t = tmp_path / "tests" / "test_one.py"
    t.parent.mkdir(parents=True, exist_ok=True)
    t.write_text("def test_x(): pass\n", encoding="utf-8")

    monkeypatch.setattr(Path, "cwd", lambda: tmp_path)
    exit_code = main(["--all"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PASS — All test files comply with test architecture standards." in out


def test_get_diff_modified_files_and_lines_mocked(tmp_path: Path, monkeypatch) -> None:
    diff_output = (
        "diff --git a/packages/tff-core/tests/test_a.py b/packages/tff-core/tests/test_a.py\n"
        "--- a/packages/tff-core/tests/test_a.py\n"
        "+++ b/packages/tff-core/tests/test_a.py\n"
        "@@ -10,0 +11,3 @@\n"
        "+line1\n"
        "+line2\n"
        "+line3\n"
    )
    untracked_output = "packages/tff-core/tests/test_new.py\nsrc/file.py\n"

    def mock_run(cmd, *args, **kwargs):
        class MockProc:
            returncode = 0
            stdout = diff_output if "diff" in cmd else untracked_output

        return MockProc()

    (tmp_path / "packages/tff-core/tests").mkdir(parents=True, exist_ok=True)
    (tmp_path / "packages/tff-core/tests/test_a.py").touch()
    (tmp_path / "packages/tff-core/tests/test_new.py").touch()

    monkeypatch.setattr("subprocess.run", mock_run)
    res = get_diff_modified_files_and_lines(tmp_path, compare_branch="origin/main")

    test_a = (tmp_path / "packages/tff-core/tests/test_a.py").resolve()
    test_new = (tmp_path / "packages/tff-core/tests/test_new.py").resolve()

    assert test_a in res
    assert res[test_a] == {11, 12, 13}
    assert test_new in res
    assert res[test_new] is None
