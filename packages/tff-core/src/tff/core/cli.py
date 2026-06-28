"""Unified command-line interface for tff."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from tff.core.config import load_fitness_config
from tff.core.context import set_ff_config
from tff.core.report import render_lint_report


def _detect_provider(project_root: Path) -> str:
    """Detect whether a project is dbt or SQLMesh."""
    # Check for dbt signature file
    is_dbt = (project_root / "dbt_project.yml").exists()

    # Check for SQLMesh signature files
    is_sqlmesh = (
        (project_root / ".sqlmesh").exists()
        or (project_root / "config.py").exists()
        or (project_root / "config.yaml").exists()
        or (project_root / "config.yml").exists()
    )

    if is_dbt and is_sqlmesh:
        raise ValueError(
            "Both dbt and SQLMesh configuration files were detected in the project root.\n"
            "Please specify the provider explicitly using the --provider option (e.g. '--provider dbt' or '--provider sqlmesh')."
        )
    if is_dbt:
        return "dbt"
    if is_sqlmesh:
        return "sqlmesh"

    raise ValueError(
        "Could not detect project type (neither dbt_project.yml nor SQLMesh config was found).\n"
        "Please run this command from your project root, or specify the provider explicitly using the --provider option."
    )


def _get_runner(provider: str) -> Any:
    """Load and return the runner module for the specified provider."""
    if provider == "dbt":
        try:
            return importlib.import_module("tff.dbt.runner")
        except ImportError as e:
            raise ImportError(
                "dbt project detected, but tff-dbt is not installed in the current environment.\n"
                "Please install it using: pip install tff-dbt"
            ) from e
    elif provider == "sqlmesh":
        try:
            return importlib.import_module("tff.sqlmesh.runner")
        except ImportError as e:
            raise ImportError(
                "SQLMesh project detected, but tff-sqlmesh is not installed in the current environment.\n"
                "Please install it using: pip install tff-sqlmesh"
            ) from e
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _parse_checks(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [part.strip() for part in value.split(",") if part.strip()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tff",
        description="Run Transformation Fitness Function (tff) checks",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    lint_parser = subparsers.add_parser("lint", help="Run all enabled fitness checks")
    lint_parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
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
        "Use 'rules' for general linter rules on dbt projects, or 'sqlmesh' on SQLMesh projects.",
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
    lint_parser.add_argument(
        "--provider",
        choices=["auto", "dbt", "sqlmesh"],
        default="auto",
        help="Pipeline engine provider (default: auto-detected)",
    )
    lint_parser.add_argument(
        "--dialect",
        default=None,
        help="SQL dialect of models (dbt only; auto-inferred by default)",
    )

    args = parser.parse_args(argv)

    if args.command == "lint":
        logging.basicConfig(level=logging.ERROR)
        project_root = args.project.resolve()

        # 1. Determine provider
        provider = args.provider
        if provider == "auto":
            try:
                provider = _detect_provider(project_root)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        # 2. Get runner (checks adapter availability)
        try:
            runner_module = _get_runner(provider)
        except (ImportError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        # 3. Load config
        try:
            config = load_fitness_config(
                project_root,
                config_path=args.config,
            )
        except Exception as e:
            print(f"Error loading configuration: {e}", file=sys.stderr)
            return 1

        set_ff_config(config)
        checks = _parse_checks(args.checks)

        # 4. Run checks
        try:
            if provider == "dbt":
                findings, models_checked, executed_checks = runner_module.run_all_checks(
                    project_root=project_root,
                    config=config,
                    checks=checks,
                    dialect=args.dialect,
                )
            else:
                if args.dialect is not None:
                    print(
                        "Warning: --dialect is ignored for SQLMesh projects (dialects are defined directly on models).",
                        file=sys.stderr,
                    )
                findings, models_checked, executed_checks = runner_module.run_all_checks(
                    project_root=project_root,
                    config=config,
                    checks=checks,
                )
        except Exception as e:
            print(f"Error executing checks: {e}", file=sys.stderr)
            return 1

        # 5. Render report
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
