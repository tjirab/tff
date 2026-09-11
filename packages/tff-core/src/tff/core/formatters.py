"""Formatters for CI/CD integrations: GitHub Actions annotations, SARIF, and JUnit XML."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any
import xml.dom.minidom as minidom
import xml.etree.ElementTree as ET

from tff.core.report import CHECK_LABELS, LintFinding, format_message


def _get_relative_path(file_path: str | Path, project_root: Path | None = None) -> str:
    """Normalize file path to a relative path with forward slashes."""
    path_obj = Path(file_path)
    if project_root is not None:
        try:
            if path_obj.is_absolute():
                rel = path_obj.relative_to(project_root.resolve())
            else:
                rel = path_obj
            return str(rel).replace("\\", "/")
        except ValueError:
            pass
    try:
        if path_obj.is_absolute():
            rel = path_obj.relative_to(Path.cwd().resolve())
            return str(rel).replace("\\", "/")
    except ValueError:
        pass
    return str(path_obj).replace("\\", "/")


def format_github_annotation(
    finding: LintFinding,
    project_root: Path | None = None,
) -> str:
    """Format a LintFinding as a GitHub Actions workflow command annotation."""
    command = "error" if finding.severity == "error" else "warning"
    msg = format_message(finding.message)
    # GitHub Actions workflow command escaping for message
    msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    if finding.path:
        file_str = _get_relative_path(finding.path, project_root)
        line_num = finding.line if finding.line is not None else 1
        return f"::{command} file={file_str},line={line_num}::{msg}"
    return f"::{command}::{msg}"


def emit_github_annotations(
    findings: list[LintFinding],
    project_root: Path | None = None,
    stream: Any = None,
) -> None:
    """Emit GitHub Actions annotations to stdout or the specified stream."""
    target_stream = stream if stream is not None else sys.stdout
    for finding in findings:
        annotation = format_github_annotation(finding, project_root=project_root)
        print(annotation, file=target_stream)


def generate_sarif_report(
    findings: list[LintFinding],
    project_root: Path | None = None,
    tool_version: str | None = None,
) -> dict[str, Any]:
    """Generate an OASIS SARIF v2.1.0 report dictionary from lint findings."""
    rules_map: dict[str, dict[str, Any]] = {}

    # Gather registered checks
    from tff.core.registry import registry

    for check_def in registry.all_checks():
        cid = check_def.finding_id
        rules_map[cid] = {
            "id": cid,
            "name": check_def.id,
            "shortDescription": {"text": check_def.label},
            "defaultConfiguration": {
                "level": "error"
                if check_def.default_severity == "error"
                else "warning"
            },
            "helpUri": "https://github.com/tjirab/tff",
        }

    # Ensure all finding checks are defined in rules_map
    for f in findings:
        if f.check not in rules_map:
            label = CHECK_LABELS.get(f.check, f.check)
            rules_map[f.check] = {
                "id": f.check,
                "name": f.check,
                "shortDescription": {"text": label},
                "defaultConfiguration": {
                    "level": "error" if f.severity == "error" else "warning"
                },
                "helpUri": "https://github.com/tjirab/tff",
            }

    sarif_rules = sorted(rules_map.values(), key=lambda r: r["id"])

    results: list[dict[str, Any]] = []
    for f in findings:
        level = "error" if f.severity == "error" else "warning"
        result: dict[str, Any] = {
            "ruleId": f.check,
            "level": level,
            "message": {"text": format_message(f.message)},
        }

        if f.path:
            rel_path = _get_relative_path(f.path, project_root)
            line_num = f.line if f.line is not None else 1
            result["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": {
                            "uri": rel_path,
                            "uriBaseId": "%SRCROOT%",
                        },
                        "region": {
                            "startLine": line_num,
                            "startColumn": 1,
                        },
                    }
                }
            ]

        if f.model:
            result["properties"] = {"model": f.model}

        results.append(result)

    return {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "tff",
                        "version": tool_version or "0.7.0",
                        "informationUri": "https://github.com/tjirab/tff",
                        "rules": sarif_rules,
                    }
                },
                "results": results,
            }
        ],
    }


def generate_junit_xml(
    findings: list[LintFinding],
    project_root: Path | None = None,
    fail_level: str = "error",
) -> str:
    """Generate a standard JUnit XML string from lint findings."""
    total_tests = len(findings) if findings else 1
    total_failures = len(findings)

    suites_elem = ET.Element(
        "testsuites",
        name="tff",
        tests=str(total_tests),
        failures=str(total_failures),
        errors="0",
        time="0.0",
    )

    suite_elem = ET.SubElement(
        suites_elem,
        "testsuite",
        name="tff.lint",
        tests=str(total_tests),
        failures=str(total_failures),
        errors="0",
        skipped="0",
        time="0.0",
        timestamp=datetime.now().astimezone().isoformat(),
    )

    if not findings:
        ET.SubElement(
            suite_elem,
            "testcase",
            classname="tff.lint",
            name="all_checks",
            time="0.0",
        )
    else:
        for f in findings:
            tc = ET.SubElement(
                suite_elem,
                "testcase",
                classname=f.model or "tff.lint",
                name=f.check,
                time="0.0",
            )
            if f.path:
                rel_path = _get_relative_path(f.path, project_root)
                tc.attrib["file"] = rel_path
                tc.attrib["line"] = str(f.line if f.line is not None else 1)

            failure = ET.SubElement(
                tc,
                "failure",
                message=format_message(f.message),
                type=f.severity,
            )
            failure.text = format_message(f.message)

    raw_xml = ET.tostring(suites_elem, encoding="utf-8")
    parsed = minidom.parseString(raw_xml)
    return parsed.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8")
