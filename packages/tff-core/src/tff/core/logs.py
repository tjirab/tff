"""Utilities for JSON serialization and local logging of tff check runs."""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Sequence

from tff.core.report import LintFinding

logger = logging.getLogger(__name__)


def serialize_finding(f: LintFinding) -> dict[str, Any]:
    """Serialize a LintFinding dataclass into a standard dictionary."""
    data: dict[str, Any] = {
        "check": f.check,
        "severity": f.severity,
        "message": f.message,
        "model": f.model,
        "path": f.path,
    }
    if getattr(f, "line", None) is not None:
        data["line"] = f.line
    return data


def get_lint_json_data(
    findings: list[LintFinding],
    models_checked: int,
    fail_level: str,
) -> dict[str, Any]:
    """Compile tff lint findings and stats into a JSON-serializable dictionary."""
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
    """Compile tff health scores and findings into a JSON-serializable dictionary."""
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

    data: dict[str, Any] = {
        "timestamp": datetime.now().astimezone().isoformat(),
        "command": "health",
        "overall_score": overall_score,
        "models_checked": models_checked,
        "category_scores": category_scores,
        "check_scores": check_scores,
        "enabled_checks": sorted(enabled_checks),
        "findings": flat_findings,
    }
    if "check_weights" in scores:
        data["check_weights"] = scores["check_weights"]
    return data


def is_logging_disabled() -> bool:
    """Return True if disk logging is disabled via environment variable."""
    return os.environ.get("TFF_NO_LOG", "").strip().lower() in ("1", "true", "yes")


def is_debug_enabled(args: Any = None) -> bool:
    """Return True if debug logging is enabled via --debug flag or TFF_DEBUG env var."""
    if args is not None and getattr(args, "debug", False):
        return True
    return os.environ.get("TFF_DEBUG", "").strip().lower() in ("1", "true", "yes")


def setup_cli_logging(debug: bool = False) -> None:
    """Configure CLI logging level and formatting for the active session."""
    level = logging.DEBUG if debug else logging.ERROR
    if debug:
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
            force=True,
        )
    else:
        logging.basicConfig(
            level=level,
            format="%(levelname)s: %(message)s",
            force=True,
        )
    logging.getLogger().setLevel(level)


def save_log(
    project_root: Path, command: str, data: dict[str, Any], no_log: bool = False
) -> Path | None:
    """Save execution JSON to .tff_logs/<command>/<timestamp>.log and clean up logs older than 60 days.

    If no_log is True or TFF_NO_LOG=1 is set, logging is bypassed and returns None.
    """
    if no_log or is_logging_disabled():
        logger.debug("Execution logging bypassed (no_log=%s)", no_log)
        return None

    log_dir = project_root / ".tff_logs" / command
    log_dir.mkdir(parents=True, exist_ok=True)

    # Format a file-safe timestamp: YYYY-MM-DDTHH-MM-SS
    # Avoid colons because they're invalid on Windows
    timestamp = datetime.now().isoformat().split(".")[0].replace(":", "-")
    log_file = log_dir / f"{timestamp}.log"

    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

    logger.debug("Saved execution log to %s", log_file)

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


def collect_stats(
    project_root: Path | Sequence[Path | str] | str,
    days: int,
) -> list[dict[str, Any]]:
    """Collect tff health and lint history over the last N days from log files."""
    from tff.core.adapter import normalize_project_roots

    roots = normalize_project_roots(project_root)

    # Generate list of dates from (today - days + 1) to today
    today = date.today()
    dates = [today - timedelta(days=d) for d in range(days - 1, -1, -1)]

    # Read all health logs and lint logs for each root
    health_logs_by_root: dict[Path, list[dict[str, Any]]] = {}
    lint_logs_by_root: dict[Path, list[dict[str, Any]]] = {}

    for root in roots:
        h_logs: list[dict[str, Any]] = []
        health_dir = root / ".tff_logs" / "health"
        if health_dir.exists():
            for file in health_dir.glob("*.log"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        dt = datetime.fromisoformat(data["timestamp"])
                        h_logs.append({
                            "dt": dt,
                            "date": dt.date(),
                            "overall_score": data.get("overall_score"),
                            "models_checked": data.get("models_checked", 0),
                        })
                except Exception:
                    pass
        h_logs.sort(key=lambda x: x["dt"])
        if h_logs:
            health_logs_by_root[root] = h_logs

        l_logs: list[dict[str, Any]] = []
        lint_dir = root / ".tff_logs" / "lint"
        if lint_dir.exists():
            for file in lint_dir.glob("*.log"):
                try:
                    with open(file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        dt = datetime.fromisoformat(data["timestamp"])
                        l_logs.append({
                            "dt": dt,
                            "date": dt.date(),
                            "errors_count": data.get("errors_count", 0),
                            "warnings_count": data.get("warnings_count", 0),
                        })
                except Exception:
                    pass
        l_logs.sort(key=lambda x: x["dt"])
        if l_logs:
            lint_logs_by_root[root] = l_logs

    # If no logs exist at all, return empty list
    if not health_logs_by_root and not lint_logs_by_root:
        return []

    history = []
    for d in dates:
        # Find latest health log on or before date d for each root
        latest_healths = []
        for root, h_logs in health_logs_by_root.items():
            latest = None
            for log in h_logs:
                if log["date"] <= d:
                    latest = log
                else:
                    break
            if latest is not None:
                latest_healths.append(latest)

        # Find latest lint log on or before date d for each root
        latest_lints = []
        for root, l_logs in lint_logs_by_root.items():
            latest = None
            for log in l_logs:
                if log["date"] <= d:
                    latest = log
                else:
                    break
            if latest is not None:
                latest_lints.append(latest)

        health_score = None
        if latest_healths:
            valid_scores = [h for h in latest_healths if h["overall_score"] is not None]
            if valid_scores:
                total_models = sum(h["models_checked"] for h in valid_scores)
                if total_models > 0:
                    combined_score = sum(
                        h["overall_score"] * h["models_checked"] for h in valid_scores
                    ) / total_models
                else:
                    combined_score = sum(h["overall_score"] for h in valid_scores) / len(valid_scores)
                health_score = round(combined_score, 2)

        errors_count = None
        warnings_count = None
        if latest_lints:
            errors_count = sum(lint_log["errors_count"] for lint_log in latest_lints)
            warnings_count = sum(lint_log["warnings_count"] for lint_log in latest_lints)

        history.append({
            "date": d.isoformat(),
            "health_score": health_score,
            "errors_count": errors_count,
            "warnings_count": warnings_count,
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

    col_spacing = 8
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

    # Add x-axis labels (dates) formatted as "MMM DD" padded to col_spacing
    formatted_dates = []
    for d_str in dates:
        try:
            dt = datetime.strptime(d_str, "%Y-%m-%d")
            formatted_dates.append(dt.strftime("%b %d").ljust(col_spacing))
        except Exception:
            formatted_dates.append(d_str[:col_spacing].ljust(col_spacing))

    date_line = " " * 7 + "".join(formatted_dates)
    lines.append(date_line)

    return "\n".join(lines)

