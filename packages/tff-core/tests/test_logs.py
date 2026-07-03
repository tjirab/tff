import os
import time
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from tff.core.report import LintFinding
from tff.core.logs import (
    serialize_finding,
    get_lint_json_data,
    get_health_json_data,
    save_log,
    collect_stats,
    render_ascii_chart,
)


def test_serialize_finding():
    finding = LintFinding(
        check="banselectstar",
        severity="error",
        message="Do not use SELECT * in marts.",
        model="model_a",
        path="models/marts/model_a.sql",
    )
    serialized = serialize_finding(finding)
    assert serialized == {
        "check": "banselectstar",
        "severity": "error",
        "message": "Do not use SELECT * in marts.",
        "model": "model_a",
        "path": "models/marts/model_a.sql",
    }


def test_get_lint_json_data():
    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            message="Error 1",
            model="model_a",
            path="models/marts/model_a.sql",
        ),
        LintFinding(
            check="columnnames",
            severity="warning",
            message="Warning 1",
            model="model_b",
            path="models/marts/model_b.sql",
        ),
    ]

    # Test passing level with fail_level="error" (fails because there's an error)
    data = get_lint_json_data(findings, models_checked=5, fail_level="error")
    assert data["command"] == "lint"
    assert data["models_checked"] == 5
    assert data["errors_count"] == 1
    assert data["warnings_count"] == 1
    assert data["passed"] is False
    assert len(data["findings"]) == 2

    # Test passing level with findings that have no errors
    only_warnings = [findings[1]]
    data_warn = get_lint_json_data(only_warnings, models_checked=3, fail_level="error")
    assert data_warn["passed"] is True

    # Test passing level with fail_level="warning" (fails because there is a warning)
    data_warn_fail = get_lint_json_data(only_warnings, models_checked=3, fail_level="warning")
    assert data_warn_fail["passed"] is False


def test_get_health_json_data():
    scores = {
        "overall_score": 85.5,
        "category_scores": {
            "Connascence of Name (CoN)": 90.0,
            "Quality & Metadata (Non-Connascence)": 81.0,
        },
        "check_scores": {
            "banselectstar": 100.0,
            "nomissingowner": 50.0,
        },
        "enabled_checks": {"banselectstar", "nomissingowner"},
        "check_findings": {
            "nomissingowner": [
                LintFinding(
                    check="nomissingowner",
                    severity="warning",
                    message="Missing owner.",
                    model="model_b",
                    path="models/marts/model_b.sql",
                )
            ]
        },
    }

    data = get_health_json_data(scores, models_checked=10)
    assert data["command"] == "health"
    assert data["overall_score"] == 85.5
    assert data["models_checked"] == 10
    assert data["category_scores"] == {
        "Connascence of Name (CoN)": 90.0,
        "Quality & Metadata (Non-Connascence)": 81.0,
    }
    assert data["check_scores"] == {
        "banselectstar": 100.0,
        "nomissingowner": 50.0,
    }
    assert data["enabled_checks"] == ["banselectstar", "nomissingowner"]
    assert len(data["findings"]) == 1
    assert data["findings"][0]["check"] == "nomissingowner"


def test_save_log_and_pruning(tmp_path: Path):
    # Setup folders under tmp_path
    lint_dir = tmp_path / ".tff_logs" / "lint"
    lint_dir.mkdir(parents=True)

    # 1. Create a log file that is 61 days old
    old_file = lint_dir / "old_run.log"
    old_file.touch()
    old_mtime = time.time() - (61 * 24 * 3600)
    os.utime(old_file, (old_mtime, old_mtime))

    # 2. Create a log file that is 10 days old
    recent_file = lint_dir / "recent_run.log"
    recent_file.touch()
    recent_mtime = time.time() - (10 * 24 * 3600)
    os.utime(recent_file, (recent_mtime, recent_mtime))

    # 3. Save a new log
    data = {"test": "data"}
    new_log_path = save_log(tmp_path, "lint", data)

    # Verify new log was written
    assert new_log_path.exists()
    assert new_log_path.parent.name == "lint"

    # Verify old file was deleted during pruning
    assert not old_file.exists()

    # Verify recent file is still kept
    assert recent_file.exists()


@patch("pathlib.Path.unlink")
def test_save_log_pruning_handles_exception(mock_unlink, tmp_path: Path):
    mock_unlink.side_effect = OSError("Permission denied")

    lint_dir = tmp_path / ".tff_logs" / "lint"
    lint_dir.mkdir(parents=True)

    old_file = lint_dir / "old_run.log"
    old_file.touch()
    old_mtime = time.time() - (61 * 24 * 3600)
    os.utime(old_file, (old_mtime, old_mtime))

    # This should not raise an exception, because it's caught and passed
    new_log_path = save_log(tmp_path, "lint", {"test": "data"})
    assert new_log_path.exists()
    mock_unlink.assert_called_once()


def test_collect_stats(tmp_path: Path):
    # Test empty log folders
    stats = collect_stats(tmp_path, days=7)
    assert stats == []

    # Setup directories
    health_dir = tmp_path / ".tff_logs" / "health"
    health_dir.mkdir(parents=True)
    lint_dir = tmp_path / ".tff_logs" / "lint"
    lint_dir.mkdir(parents=True)

    # Helper to write log with timestamp
    def write_log(directory, filename, timestamp, payload):
        log_file = directory / filename
        data = {"timestamp": timestamp, **payload}
        import json
        with open(log_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

    # Write some logs
    # 2 days ago:
    two_days_ago_dt = datetime.now() - timedelta(days=2)
    write_log(health_dir, "h1.log", two_days_ago_dt.astimezone().isoformat(), {"overall_score": 90.0})
    write_log(lint_dir, "l1.log", two_days_ago_dt.astimezone().isoformat(), {"errors_count": 1, "warnings_count": 0})

    # Today (first run):
    today_dt_1 = datetime.now() - timedelta(minutes=10)
    write_log(health_dir, "h2.log", today_dt_1.astimezone().isoformat(), {"overall_score": 95.0})
    # Today (second run):
    today_dt_2 = datetime.now()
    write_log(health_dir, "h3.log", today_dt_2.astimezone().isoformat(), {"overall_score": 98.0})
    write_log(lint_dir, "l2.log", today_dt_2.astimezone().isoformat(), {"errors_count": 0, "warnings_count": 1})

    stats = collect_stats(tmp_path, days=3)
    assert len(stats) == 3

    # Check today-2
    assert stats[0]["health_score"] == 90.0
    assert stats[0]["errors_count"] == 1
    assert stats[0]["warnings_count"] == 0

    # Check today-1 (carried forward)
    assert stats[1]["health_score"] == 90.0
    assert stats[1]["errors_count"] == 1
    assert stats[1]["warnings_count"] == 0

    # Check today (final run of today)
    assert stats[2]["health_score"] == 98.0
    assert stats[2]["errors_count"] == 0
    assert stats[2]["warnings_count"] == 1


def test_render_ascii_chart():
    # Test no data
    assert render_ascii_chart([], [], height=5) == "  (No data)"

    # Test single point/flat line
    dates = ["2026-07-01", "2026-07-02"]
    values = [90.0, 90.0]
    chart = render_ascii_chart(values, dates, height=5, is_percentage=True)
    assert "90.0%" in chart
    assert "●" in chart
    assert "─" in chart

    # Test non-percentage rendering (e.g. violation counts)
    chart_non_pct = render_ascii_chart(values, dates, height=5, is_percentage=False)
    assert "   90 " in chart_non_pct
    assert "●" in chart_non_pct

    # Test invalid dates fall back gracefully
    invalid_dates = ["invalid-date-1", "invalid-date-2"]
    chart_invalid_dates = render_ascii_chart(values, invalid_dates, height=5, is_percentage=True)
    assert "invali" in chart_invalid_dates

    # Test values going up
    values_up = [80.0, 100.0]
    chart_up = render_ascii_chart(values_up, dates, height=3, is_percentage=True)
    assert "●" in chart_up
    assert "╭" in chart_up or "╯" in chart_up or "│" in chart_up

    # Test values going down
    values_down = [100.0, 80.0]
    chart_down = render_ascii_chart(values_down, dates, height=3, is_percentage=True)
    assert "●" in chart_down
    assert "╮" in chart_down or "╰" in chart_down or "│" in chart_down


def test_collect_stats_corrupt_files(tmp_path: Path):
    health_dir = tmp_path / ".tff_logs" / "health"
    health_dir.mkdir(parents=True)
    lint_dir = tmp_path / ".tff_logs" / "lint"
    lint_dir.mkdir(parents=True)

    # Write corrupt JSON files
    with open(health_dir / "corrupt.log", "w", encoding="utf-8") as f:
        f.write("invalid json content")
    with open(lint_dir / "corrupt.log", "w", encoding="utf-8") as f:
        f.write("invalid json content")

    # Collect stats (should pass without raising exceptions, and return empty list since no valid logs exist)
    stats = collect_stats(tmp_path, days=7)
    assert stats == []



