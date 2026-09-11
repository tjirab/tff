"""Unit tests for CI/CD formatters (GitHub Actions annotations, SARIF v2.1.0, JUnit XML)."""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
from pathlib import Path

from tff.core.formatters import (
    _get_relative_path,
    emit_github_annotations,
    format_github_annotation,
    generate_junit_xml,
    generate_sarif_report,
)
from tff.core.report import LintFinding


def test_get_relative_path_project_root(tmp_path: Path):
    root = tmp_path / "my_project"
    root.mkdir()
    file_path = root / "models" / "staging" / "stg_users.sql"
    file_path.parent.mkdir(parents=True)
    file_path.touch()

    # Relative to project_root
    assert (
        _get_relative_path(file_path, project_root=root)
        == "models/staging/stg_users.sql"
    )

    # Already relative string
    assert (
        _get_relative_path("models/staging/stg_users.sql", project_root=root)
        == "models/staging/stg_users.sql"
    )


def test_get_relative_path_outside_project_root(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    other = tmp_path / "other" / "file.sql"

    # Outside project_root, outside cwd -> fallback to str
    rel = _get_relative_path(other, project_root=root)
    assert rel == str(other).replace("\\", "/")

    # No project_root given, outside cwd
    rel2 = _get_relative_path(other)
    assert rel2 == str(other).replace("\\", "/")


def test_get_relative_path_inside_cwd():
    cwd_file = Path.cwd() / "some_dir" / "model.sql"
    assert _get_relative_path(cwd_file) == "some_dir/model.sql"


def test_format_github_annotation_error_and_warning():
    f_err = LintFinding(
        check="duplicate_ctes",
        severity="error",
        message="Duplicate CTE found in model.",
        model="fct_orders",
        path="models/marts/fct_orders.sql",
        line=42,
    )
    res_err = format_github_annotation(f_err)
    assert (
        res_err
        == "::error file=models/marts/fct_orders.sql,line=42::Duplicate CTE found in model."
    )

    f_warn = LintFinding(
        check="mart_naming",
        severity="warning",
        message="Model in marts must start with fct_ or dim_.",
        model="bad_name",
        path="models/marts/bad_name.sql",
    )
    res_warn = format_github_annotation(f_warn)
    # When line is not provided, it defaults to line 1
    assert (
        res_warn
        == "::warning file=models/marts/bad_name.sql,line=1::Model in marts must start with fct_ or dim_."
    )


def test_format_github_annotation_repo_level_no_path():
    f_repo = LintFinding(
        check="layer_integrity",
        severity="error",
        message="Missing layers in config.",
    )
    res = format_github_annotation(f_repo)
    assert res == "::error::Missing layers in config."


def test_format_github_annotation_escaping():
    f = LintFinding(
        check="sqlcomplexity",
        severity="warning",
        message="High complexity: 100% (target < 80%)\nLine 2 details\rLine 3",
        path="models/model.sql",
    )
    res = format_github_annotation(f)
    assert "%25" in res
    assert "%0A" in res
    assert "%0D" in res
    assert "\n" not in res


def test_emit_github_annotations():
    findings = [
        LintFinding(
            check="c1",
            severity="error",
            message="Error 1",
            path="models/a.sql",
            line=10,
        ),
        LintFinding(
            check="c2",
            severity="warning",
            message="Warning 1",
            path="models/b.sql",
        ),
    ]
    stream = io.StringIO()
    emit_github_annotations(findings, stream=stream)
    output = stream.getvalue()
    lines = output.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "::error file=models/a.sql,line=10::Error 1"
    assert lines[1] == "::warning file=models/b.sql,line=1::Warning 1"


def test_generate_sarif_report_structure(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    sql_file = root / "models" / "a.sql"
    sql_file.parent.mkdir()
    sql_file.touch()

    findings = [
        LintFinding(
            check="duplicate_ctes",
            severity="error",
            message="Duplicate CTE found.",
            model="a",
            path=str(sql_file),
            line=15,
        ),
        LintFinding(
            check="custom_rule",
            severity="warning",
            message="Custom warning message.",
            model="b",
            path=None,
        ),
    ]

    report = generate_sarif_report(
        findings, project_root=root, tool_version="1.2.3"
    )

    assert (
        report["$schema"]
        == "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
    )
    assert report["version"] == "2.1.0"
    assert len(report["runs"]) == 1

    run = report["runs"][0]
    driver = run["tool"]["driver"]
    assert driver["name"] == "tff"
    assert driver["version"] == "1.2.3"
    assert driver["informationUri"] == "https://github.com/tjirab/tff"

    rule_ids = [r["id"] for r in driver["rules"]]
    assert "duplicate_ctes" in rule_ids
    assert "custom_rule" in rule_ids

    results = run["results"]
    assert len(results) == 2

    r0 = results[0]
    assert r0["ruleId"] == "duplicate_ctes"
    assert r0["level"] == "error"
    assert r0["message"]["text"] == "Duplicate CTE found."
    assert r0["properties"]["model"] == "a"
    assert len(r0["locations"]) == 1
    loc0 = r0["locations"][0]["physicalLocation"]
    assert loc0["artifactLocation"]["uri"] == "models/a.sql"
    assert loc0["artifactLocation"]["uriBaseId"] == "%SRCROOT%"
    assert loc0["region"]["startLine"] == 15
    assert loc0["region"]["startColumn"] == 1

    r1 = results[1]
    assert r1["ruleId"] == "custom_rule"
    assert r1["level"] == "warning"
    assert "locations" not in r1


def test_generate_sarif_report_empty():
    report = generate_sarif_report([], tool_version="0.7.0")
    assert report["version"] == "2.1.0"
    run = report["runs"][0]
    assert run["results"] == []


def test_generate_junit_xml_empty():
    xml_str = generate_junit_xml([])
    root = ET.fromstring(xml_str)
    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "1"
    assert root.attrib["failures"] == "0"
    assert root.attrib["errors"] == "0"

    suite = root.find("testsuite")
    assert suite is not None
    assert suite.attrib["name"] == "tff.lint"
    assert suite.attrib["tests"] == "1"
    assert suite.attrib["failures"] == "0"

    tc = suite.find("testcase")
    assert tc is not None
    assert tc.attrib["name"] == "all_checks"
    assert tc.attrib["classname"] == "tff.lint"


def test_generate_junit_xml_with_findings(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    sql_file = root / "models" / "orders.sql"
    sql_file.parent.mkdir()
    sql_file.touch()

    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="orders",
            path=str(sql_file),
            line=5,
        ),
        LintFinding(
            check="layer_integrity",
            severity="warning",
            message="Cross-layer dependency warning.",
            model=None,
            path=None,
        ),
    ]

    xml_str = generate_junit_xml(findings, project_root=root)
    tree_root = ET.fromstring(xml_str)

    assert tree_root.attrib["tests"] == "2"
    assert tree_root.attrib["failures"] == "2"

    suite = tree_root.find("testsuite")
    assert suite is not None
    assert suite.attrib["tests"] == "2"
    assert suite.attrib["failures"] == "2"

    testcases = suite.findall("testcase")
    assert len(testcases) == 2

    # First testcase: model="orders", check="banselectstar"
    tc0 = testcases[0]
    assert tc0.attrib["classname"] == "orders"
    assert tc0.attrib["name"] == "banselectstar"
    assert tc0.attrib["file"] == "models/orders.sql"
    assert tc0.attrib["line"] == "5"

    failure0 = tc0.find("failure")
    assert failure0 is not None
    assert failure0.attrib["type"] == "error"
    assert failure0.attrib["message"] == "SELECT * is prohibited."
    assert failure0.text == "SELECT * is prohibited."

    # Second testcase: no model, no path
    tc1 = testcases[1]
    assert tc1.attrib["classname"] == "tff.lint"
    assert tc1.attrib["name"] == "layer_integrity"
    assert "file" not in tc1.attrib

    failure1 = tc1.find("failure")
    assert failure1 is not None
    assert failure1.attrib["type"] == "warning"
