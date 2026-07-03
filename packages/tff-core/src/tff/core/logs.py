"""Utilities for JSON serialization and local logging of TFF check runs."""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from tff.core.report import LintFinding


def serialize_finding(f: LintFinding) -> dict[str, Any]:
    """Serialize a LintFinding dataclass into a standard dictionary."""
    return {
        "check": f.check,
        "severity": f.severity,
        "message": f.message,
        "model": f.model,
        "path": f.path,
    }


def get_lint_json_data(
    findings: list[LintFinding],
    models_checked: int,
    fail_level: str,
) -> dict[str, Any]:
    """Compile TFF lint findings and stats into a JSON-serializable dictionary."""
    errors = [f for f in findings if f.severity == "error"]
    warnings = [f for f in findings if f.severity == "warning"]

    # passed is True if:
    # 1. No errors.
    # 2. No warnings if fail_level is "warning".
    passed = not (
        any(f.severity == "error" for f in findings)
        or (fail_level == "warning" and any(f.severity == "warning" for f in findings))
    )

    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "command": "lint",
        "models_checked": models_checked,
        "errors_count": len(errors),
        "warnings_count": len(warnings),
        "passed": passed,
        "findings": [serialize_finding(f) for f in findings],
    }


def get_health_json_data(
    scores: dict[str, Any],
    models_checked: int,
) -> dict[str, Any]:
    """Compile TFF health scores and findings into a JSON-serializable dictionary."""
    overall_score = scores["overall_score"]
    category_scores = scores["category_scores"]
    check_scores = scores["check_scores"]
    enabled_checks = list(scores["enabled_checks"])
    check_findings = scores["check_findings"]

    flat_findings: list[dict[str, Any]] = []
    for findings_list in check_findings.values():
        for f in findings_list:
            flat_findings.append(serialize_finding(f))

    # Sort findings by model, check, severity for deterministic output
    flat_findings.sort(key=lambda x: (x["model"] or "", x["check"], x["severity"]))

    return {
        "timestamp": datetime.now().astimezone().isoformat(),
        "command": "health",
        "overall_score": overall_score,
        "models_checked": models_checked,
        "category_scores": category_scores,
        "check_scores": check_scores,
        "enabled_checks": sorted(enabled_checks),
        "findings": flat_findings,
    }


def save_log(project_root: Path, command: str, data: dict[str, Any]) -> Path:
    """Save execution JSON to .tff_logs/<command>/<timestamp>.log and clean up logs older than 60 days."""
    log_dir = project_root / ".tff_logs" / command
    log_dir.mkdir(parents=True, exist_ok=True)

    # Format a file-safe timestamp: YYYY-MM-DDTHH-MM-SS
    # Avoid colons because they're invalid on Windows
    timestamp = datetime.now().isoformat().split(".")[0].replace(":", "-")
    log_file = log_dir / f"{timestamp}.log"

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    # Clean up logs older than 60 days in both lint/health dirs
    limit = time.time() - (60 * 24 * 3600)
    base_log_dir = project_root / ".tff_logs"
    if base_log_dir.exists():
        for cmd_dir in base_log_dir.iterdir():
            if cmd_dir.is_dir() and cmd_dir.name in ("lint", "health"):
                for file in cmd_dir.glob("*.log"):
                    try:
                        if file.stat().st_mtime < limit:
                            file.unlink()
                    except Exception:
                        pass

    return log_file
