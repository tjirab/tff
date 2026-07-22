"""Utilities for JSON serialization and local logging of TFF check runs."""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
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


def collect_stats(project_root: Path, days: int) -> list[dict[str, Any]]:
    """Collect TFF health and lint history over the last N days from log files."""
    # Generate list of dates from (today - days + 1) to today
    today = date.today()
    dates = [today - timedelta(days=d) for d in range(days - 1, -1, -1)]

    # Read all health logs and sort them by timestamp
    health_logs: list[dict[str, Any]] = []
    health_dir = project_root / ".tff_logs" / "health"
    if health_dir.exists():
        for file in health_dir.glob("*.log"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    dt = datetime.fromisoformat(data["timestamp"])
                    health_logs.append({
                        "dt": dt,
                        "date": dt.date(),
                        "overall_score": data.get("overall_score")
                    })
            except Exception:
                pass
    health_logs.sort(key=lambda x: x["dt"])

    # Read all lint logs and sort by timestamp
    lint_logs: list[dict[str, Any]] = []
    lint_dir = project_root / ".tff_logs" / "lint"
    if lint_dir.exists():
        for file in lint_dir.glob("*.log"):
            try:
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    dt = datetime.fromisoformat(data["timestamp"])
                    lint_logs.append({
                        "dt": dt,
                        "date": dt.date(),
                        "errors_count": data.get("errors_count", 0),
                        "warnings_count": data.get("warnings_count", 0)
                    })
            except Exception:
                pass
    lint_logs.sort(key=lambda x: x["dt"])

    # If no logs exist at all, return empty list
    if not health_logs and not lint_logs:
        return []

    history = []
    for d in dates:
        # Find latest health log on or before date d
        latest_health = None
        for log in health_logs:
            if log["date"] <= d:
                latest_health = log
            else:
                break

        # Find latest lint log on or before date d
        latest_lint = None
        for log in lint_logs:
            if log["date"] <= d:
                latest_lint = log
            else:
                break

        history.append({
            "date": d.isoformat(),
            "health_score": latest_health["overall_score"] if latest_health else None,
            "errors_count": latest_lint["errors_count"] if latest_lint else None,
            "warnings_count": latest_lint["warnings_count"] if latest_lint else None,
        })

    return history


def render_ascii_chart(
    values: list[float | None],
    dates: list[str],
    height: int = 6,
    is_percentage: bool = False
) -> str:
    """Render a line chart in ASCII connecting points with box drawing characters."""
    valid_values = [v for v in values if v is not None]
    if not valid_values:
        return "  (No data)"

    min_val = min(valid_values)
    max_val = max(valid_values)

    # If all values are the same, expand the range to make it look nice
    if min_val == max_val:
        min_val = max(0.0, min_val - 5.0)
        max_val = min_val + 10.0

    col_spacing = 6
    num_cols = (len(values) - 1) * col_spacing + 1
    grid = [[" " for _ in range(num_cols)] for _ in range(height)]

    # Map values to row indexes
    points = []
    for i, val in enumerate(values):
        x = i * col_spacing
        if val is None:
            points.append(None)
            continue
        ratio = (val - min_val) / (max_val - min_val)
        y = int(round((1.0 - ratio) * (height - 1)))
        grid[y][x] = "●"
        points.append((x, y))

    # Draw connections
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i+1]
        if p1 is None or p2 is None:
            continue
        x1, y1 = p1
        x2, y2 = p2

        x_mid = x1 + col_spacing // 2

        if y1 == y2:
            for x in range(x1 + 1, x2):
                grid[y1][x] = "─"
        elif y1 < y2:  # going down in grid row index (decreasing value)
            for x in range(x1 + 1, x_mid):
                grid[y1][x] = "─"
            grid[y1][x_mid] = "╮"
            for y in range(y1 + 1, y2):
                grid[y][x_mid] = "│"
            grid[y2][x_mid] = "╰"
            for x in range(x_mid + 1, x2):
                grid[y2][x] = "─"
        else:  # going up in grid row index (increasing value)
            for x in range(x1 + 1, x_mid):
                grid[y1][x] = "─"
            grid[y1][x_mid] = "╯"
            for y in range(y2 + 1, y1):
                grid[y][x_mid] = "│"
            grid[y2][x_mid] = "╭"
            for x in range(x_mid + 1, x2):
                grid[y2][x] = "─"

    lines = []
    for r in range(height):
        ratio = 1.0 - r / (height - 1)
        val = min_val + ratio * (max_val - min_val)

        # Format label to be exactly 6 characters
        if is_percentage:
            label = f"{val:5.1f}%"
        else:
            label = f"{int(round(val)):5d} "

        row_str = "".join(grid[r])
        lines.append(f"{label} │ {row_str}")

    # Add x-axis line
    lines.append("       └" + "─" * (num_cols + 1))

    # Add x-axis labels (dates) formatted as "MMM DD" (6 characters)
    formatted_dates = []
    for d_str in dates:
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            formatted_dates.append(dt.strftime("%b %d"))
        except Exception:
            formatted_dates.append(d_str[:6].ljust(6))

    date_line = " " * 7 + "".join(formatted_dates)
    lines.append(date_line)

    return "\n".join(lines)

