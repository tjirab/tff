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


def _format_annotation_title(check: str) -> str:
    """Format human-friendly rule label and connascence category for annotation title."""
    from tff.core.report import CONNASCENCE_CATEGORIES

    label = CHECK_LABELS.get(check, check)
    category = CONNASCENCE_CATEGORIES.get(check)
    if category:
        clean_cat = category.split(" (")[0]
        return f"{label} ({clean_cat})"
    return label


def format_github_annotation(
    finding: LintFinding,
    project_root: Path | None = None,
) -> str:
    """Format a LintFinding as a GitHub Actions workflow command annotation."""
    from tff.core.registry import registry

    command = "error" if finding.severity == "error" else "warning"
    msg = format_message(finding.message)
    docs_url = registry.get_docs_url(finding.check)
    if docs_url and docs_url not in msg:
        msg = f"{msg} ({docs_url})"

    # GitHub Actions workflow command escaping for message
    msg = msg.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")

    title = _format_annotation_title(finding.check)

    params: list[str] = []
    if finding.path:
        file_str = _get_relative_path(finding.path, project_root)
        line_num = finding.line if finding.line is not None else 1
        params.append(f"file={file_str}")
        params.append(f"line={line_num}")
        if finding.end_line is not None:
            params.append(f"endLine={finding.end_line}")
        if finding.col is not None:
            params.append(f"col={finding.col}")
        if finding.end_col is not None:
            params.append(f"endColumn={finding.end_col}")

    params.append(f"title={title}")

    param_str = f" {','.join(params)}" if params else ""
    return f"::{command}{param_str}::{msg}"


def _is_finding_in_modified_files(
    finding: LintFinding,
    modified_files: set[str],
    project_root: Path | None = None,
) -> bool:
    """Check whether a finding matches any file in modified_files."""
    if not modified_files:
        return False

    raw_path = finding.path
    path_str = str(raw_path or "").replace("\\", "/")
    rel_proj_str = _get_relative_path(path_str, project_root) if (path_str and project_root is not None) else path_str

    for mf in modified_files:
        norm_mf = mf.replace("\\", "/")
        if path_str and (norm_mf == path_str or norm_mf.endswith(f"/{path_str}")):
            return True
        if rel_proj_str and (norm_mf == rel_proj_str or norm_mf.endswith(f"/{rel_proj_str}")):
            return True
        if finding.model and Path(norm_mf).stem == finding.model:
            return True
    return False


def emit_github_annotations(
    findings: list[LintFinding],
    project_root: Path | None = None,
    stream: Any = None,
    modified_files: set[str] | None = None,
    max_annotations: int = 50,
) -> None:
    """Emit GitHub Actions annotations with priority sorting and capping."""
    target_stream = stream if stream is not None else sys.stdout

    mod_files = modified_files or set()

    # Prioritize: violations in modified files first, then errors before warnings
    def _priority_key(f: LintFinding) -> tuple[int, int]:
        in_modified = 0 if _is_finding_in_modified_files(f, mod_files, project_root) else 1
        sev_order = 0 if f.severity == "error" else 1
        return (in_modified, sev_order)

    sorted_findings = sorted(findings, key=_priority_key)

    total_count = len(sorted_findings)
    if total_count > max_annotations:
        notice = (
            f"::warning::tff found {total_count} violations. "
            f"Displaying the {max_annotations} highest-priority annotations; "
            f"see Job Summary or PR comment for the complete list."
        )
        print(notice, file=target_stream)
        sorted_findings = sorted_findings[:max_annotations]

    for finding in sorted_findings:
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

    default_docs_url = "https://tff.readthedocs.io/en/latest/rules_and_checks/"
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
            "helpUri": check_def.docs_url or default_docs_url,
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
                "helpUri": registry.get_docs_url(f.check) or default_docs_url,
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
