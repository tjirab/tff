"""Unified command-line interface for tff."""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from pathlib import Path
from typing import Any

from tff.core.config import load_fitness_config, resolve_project_path
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


class TFFArgumentParser(argparse.ArgumentParser):
    _current_argv: list[str] | None = None

    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        sys.stderr.write(f"{self.prog}: error: {message}\n")

        hint_cmd = self.prog
        # If the prog is already subcommand-specific (e.g. 'tff lint'), use it.
        # Otherwise, check the arguments to see if a subcommand was targetted.
        if hint_cmd == "tff" and TFFArgumentParser._current_argv is not None:
            for sub in ("lint", "health", "info", "help"):
                if sub in TFFArgumentParser._current_argv:
                    hint_cmd = f"tff {sub}"
                    break
        elif hint_cmd == "tff":
            for sub in ("lint", "health", "info", "help"):
                if sub in sys.argv:
                    hint_cmd = f"tff {sub}"
                    break

        sys.stderr.write(f"For help, try '{hint_cmd} --help'\n")
        self.exit(2)


def main(argv: list[str] | None = None) -> int:
    TFFArgumentParser._current_argv = argv
    parser = TFFArgumentParser(
        prog="tff",
        description="Run Transformation Fitness Function (tff) checks",
    )
    subparsers = parser.add_subparsers(
        dest="command", required=True, parser_class=TFFArgumentParser
    )

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

    health_parser = subparsers.add_parser(
        "health", help="Show project health report and scores"
    )
    health_parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )
    health_parser.add_argument(
        "--config",
        default="fitness_functions.yaml",
        help="Path to fitness_functions.yaml (relative to project root)",
    )
    health_parser.add_argument(
        "--provider",
        choices=["auto", "dbt", "sqlmesh"],
        default="auto",
        help="Pipeline engine provider (default: auto-detected)",
    )
    health_parser.add_argument(
        "--dialect",
        default=None,
        help="SQL dialect of models (dbt only; auto-inferred by default)",
    )
    health_parser.add_argument(
        "--fail-under",
        type=float,
        default=0.0,
        help="Exit non-zero when overall health score is below this threshold (0-100)",
    )

    # Info subcommand
    info_parser = subparsers.add_parser(
        "info",
        help="Show configuration and environment information",
        description="Show configuration and environment information",
    )
    info_parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )
    info_parser.add_argument(
        "--config",
        default="fitness_functions.yaml",
        help="Path to fitness_functions.yaml (relative to project root)",
    )
    info_parser.add_argument(
        "--provider",
        choices=["auto", "dbt", "sqlmesh"],
        default="auto",
        help="Pipeline engine provider (default: auto-detected)",
    )

    help_parser = subparsers.add_parser("help", help="Show help details for a command")
    help_parser.add_argument(
        "subcommand",
        nargs="?",
        choices=["lint", "health", "info"],
        help="Specific command to get help for",
    )

    args = parser.parse_args(argv)

    if args.command == "help":
        if args.subcommand == "lint":
            lint_parser.print_help()
        elif args.subcommand == "health":
            health_parser.print_help()
        elif args.subcommand == "info":
            info_parser.print_help()
        else:
            parser.print_help()
        return 0

    # Register target project's virtualenv site-packages if present
    if hasattr(args, "project") and args.project:
        import site

        project_root = Path(args.project).resolve()
        for venv_name in (".venv", "venv", "env"):
            venv_dir = project_root / venv_name
            if venv_dir.is_dir():
                # Unix
                libs_dir = venv_dir / "lib"
                if libs_dir.is_dir():
                    for p in libs_dir.glob("python*/site-packages"):
                        if p.is_dir():
                            site.addsitedir(str(p))
                # Windows
                win_lib = venv_dir / "Lib" / "site-packages"
                if win_lib.is_dir():
                    site.addsitedir(str(win_lib))

    if args.command == "info":
        # Run info command: show diagnostics
        from rich.console import Console
        from rich.table import Table
        import importlib.metadata as metadata

        console = Console()
        project_root = args.project.resolve()
        provider = args.provider
        if provider == "auto":
            try:
                provider = _detect_provider(project_root)
            except Exception as e:
                console.print(f"[red]Error detecting provider: {e}[/red]")
                return 1
        config_path = args.config
        resolved_config = (
            project_root / config_path
            if not Path(config_path).is_absolute()
            else Path(config_path)
        )
        config_exists = resolved_config.is_file()
        logo = (
            "  [dim]_[/dim]    [dim]_[/dim][green]_[/green]  [green]_[/green][cyan]_[/cyan]\n"
            " [dim]|[/dim] [dim]|[/dim][dim]_[/dim] [dim]/[/dim] [green]_[/green][green]|[/green][green]/[/green] [green]_[/green][cyan]|[/cyan]\n"
            " [dim]|[/dim] [dim]_[/dim][dim]_[/dim][dim]|[/dim] [green]|[/green][green]_[/green][green]|[/green] [green]|[/green][cyan]_[/cyan]\n"
            " [cyan]|[/cyan] [green]|[/green][green]_[/green][green]|[/green]  [dim]_[/dim][dim]|[/dim]  [dim]_[/dim][dim]|[/dim]\n"
            "  [cyan]\\\\[/cyan][green]_[/green][green]_[/green][green]|[/green][green]_[/green][dim]|[/dim] [dim]|[/dim][dim]_[/dim][dim]|[/dim]"
        )
        console.print(logo)
        console.print()
        console.print("[bold]TFF Info[/bold]")
        table = Table(show_header=False, box=None)
        table.add_row("Project root:", str(project_root))
        table.add_row("Provider:", provider)
        table.add_row(
            "Config file:", f"{args.config} ({'found' if config_exists else 'missing'})"
        )
        if config_exists:
            try:
                cfg = load_fitness_config(project_root, config_path)
                contract_path = resolve_project_path(cfg, cfg.contract_groups_path)
                exclusions_path = resolve_project_path(cfg, cfg.exclusions_path)
                table.add_row(
                    "Contract groups:",
                    f"{contract_path} ({'found' if contract_path.exists() else 'missing'})",
                )
                table.add_row(
                    "Exclusions:",
                    f"{exclusions_path} ({'found' if exclusions_path.exists() else 'missing'})",
                )
            except Exception as e:
                console.print(f"[yellow]Failed to load config: {e}[/yellow]")
        console.print(table)

        console.print("\n[bold]Adapter Versions[/bold]")
        target_site_packages = []
        for venv_name in (".venv", "venv", "env"):
            venv_dir = project_root / venv_name
            if venv_dir.is_dir():
                # Unix
                libs_dir = venv_dir / "lib"
                if libs_dir.is_dir():
                    for p in libs_dir.glob("python*/site-packages"):
                        if p.is_dir():
                            target_site_packages.append(str(p))
                # Windows
                win_lib = venv_dir / "Lib" / "site-packages"
                if win_lib.is_dir():
                    target_site_packages.append(str(win_lib))

        def get_version(pkg: str) -> str:
            try:
                if target_site_packages:
                    dists = metadata.distributions(path=target_site_packages)
                    for dist in dists:
                        name = dist.metadata.get("Name")
                        if name and (
                            name == pkg
                            or name.replace("_", "-") == pkg.replace("_", "-")
                        ):
                            return dist.version
                    return "not installed"
                return metadata.version(pkg)
            except Exception:
                return "not installed"

        ver_table = Table(show_header=False, box=None)
        ver_table.add_row("tff-core", get_version("tff-core"))
        ver_table.add_row("tff-dbt", get_version("tff-dbt"))
        ver_table.add_row("tff-sqlmesh", get_version("tff-sqlmesh"))
        console.print(ver_table)

        prov_table = Table(show_header=False, box=None)
        if provider == "dbt":
            dbt_project = project_root / "dbt_project.yml"
            manifest = project_root / "target" / "manifest.json"
            prov_table.add_row(
                "dbt_project.yml",
                f"{dbt_project} ({'found' if dbt_project.exists() else 'missing'})",
            )
            prov_table.add_row(
                "manifest.json",
                f"{manifest} ({'found' if manifest.exists() else 'missing'})",
            )
        elif provider == "sqlmesh":
            config_py = project_root / "config.py"
            settings_yaml = project_root / "settings.yaml"
            prov_table.add_row(
                "config.py",
                f"{config_py} ({'found' if config_py.exists() else 'missing'})",
            )
            prov_table.add_row(
                "settings.yaml",
                f"{settings_yaml} ({'found' if settings_yaml.exists() else 'missing'})",
            )
        if prov_table.row_count > 0:
            console.print("\n[bold]Provider Files[/bold]")
            console.print(prov_table)
        return 0

    if args.command in ("lint", "health"):
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
        if args.command == "lint":
            checks = _parse_checks(args.checks)
        else:
            checks = None  # Always run all checks for health report

        # 4. Run checks
        try:
            if provider == "dbt":
                findings, models_checked, executed_checks = (
                    runner_module.run_all_checks(
                        project_root=project_root,
                        config=config,
                        checks=checks,
                        dialect=args.dialect,
                    )
                )
            else:
                if args.dialect is not None:
                    print(
                        "Warning: --dialect is ignored for SQLMesh projects (dialects are defined directly on models).",
                        file=sys.stderr,
                    )
                findings, models_checked, executed_checks = (
                    runner_module.run_all_checks(
                        project_root=project_root,
                        config=config,
                        checks=checks,
                    )
                )
        except Exception as e:
            print(f"Error executing checks: {e}", file=sys.stderr)
            return 1

        if args.command == "lint":
            # 5. Render report
            passed = render_lint_report(
                findings,
                models_checked=models_checked,
                executed_checks=executed_checks,
                fail_level=args.fail_level,  # type: ignore[arg-type]
                group_by=args.group_by,  # type: ignore[arg-type]
            )
            return 0 if passed else 1
        else:
            # health command
            from tff.core.health import calculate_health_scores, render_health_report

            scores = calculate_health_scores(findings, models_checked, config, provider)
            render_health_report(scores, config, provider)

            overall_score = scores["overall_score"]
            if args.fail_under > 0.0 and overall_score < args.fail_under:
                print(
                    f"Error: Project health score {overall_score:.1f}% is below threshold {args.fail_under:.1f}%",
                    file=sys.stderr,
                )
                return 1
            return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
