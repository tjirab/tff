"""Command-line interface for sqlmesh-ff."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from sqlmesh_ff.config import load_fitness_config
from sqlmesh_ff.context import set_ff_config
from sqlmesh_ff.report import render_lint_report
from sqlmesh_ff.runner import run_all_checks


def _parse_checks(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sqlmesh-ff",
        description="Run SQLMesh fitness function checks",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint_parser = subparsers.add_parser("lint", help="Run all enabled fitness checks")
    lint_parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="SQLMesh project root (default: current directory)",
    )
    lint_parser.add_argument(
        "--config",
        default="fitness_functions.yaml",
        help="Path to fitness_functions.yaml (relative to project root)",
    )
    lint_parser.add_argument(
        "--checks",
        default=None,
        help="Comma-separated checks to run (default: all enabled). "
        "Use 'sqlmesh' for SQLMesh linter rules only.",
    )
    lint_parser.add_argument(
        "--fail-level",
        choices=["error", "warning"],
        default="error",
        help="Exit non-zero when findings at or above this severity exist",
    )
    lint_parser.add_argument(
        "--group-by",
        choices=["connascence", "model"],
        default="connascence",
        help="How to group violations in the report (default: connascence)",
    )

    args = parser.parse_args(argv)

    if args.command == "lint":
        logging.basicConfig(level=logging.ERROR)
        project_root = args.project.resolve()
        config = load_fitness_config(
            project_root,
            config_path=args.config,
        )
        set_ff_config(config)
        checks = _parse_checks(args.checks)

        findings, models_checked, executed_checks = run_all_checks(
            project_root=project_root,
            config=config,
            checks=checks,
        )
        passed = render_lint_report(
            findings,
            models_checked=models_checked,
            executed_checks=executed_checks,
            fail_level=args.fail_level,  # type: ignore[arg-type]
            group_by=args.group_by,  # type: ignore[arg-type]
        )
        return 0 if passed else 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
