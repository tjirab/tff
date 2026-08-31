"""Unified command-line interface for tff."""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import logging
import sys
from pathlib import Path
from typing import Any

from tff.core.config import load_fitness_config, resolve_project_path
from tff.core.context import set_ff_config
from tff.core.report import render_lint_report

try:
    __version__ = importlib.metadata.version("tff-core")
except Exception:
    __version__ = "0.7.0"


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
                "dbt project detected, but tff is not installed with dbt support.\n"
                'Please install it using: pip install "tff-core[dbt]" or uv add "tff-core[dbt]"'
            ) from e
    elif provider == "sqlmesh":
        try:
            return importlib.import_module("tff.sqlmesh.runner")
        except ImportError as e:
            raise ImportError(
                "SQLMesh project detected, but tff is not installed with sqlmesh support.\n"
                'Please install it using: pip install "tff-core[sqlmesh]" or uv add "tff-core[sqlmesh]"'
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
            for sub in ("lint", "health", "info", "help", "stats"):
                if sub in TFFArgumentParser._current_argv:
                    hint_cmd = f"tff {sub}"
                    break
        elif hint_cmd == "tff":
            for sub in ("lint", "health", "info", "help", "stats"):
                if sub in sys.argv:
                    hint_cmd = f"tff {sub}"
                    break

        sys.stderr.write(f"For help, try '{hint_cmd} --help'\n")
        self.exit(2)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        args_list = sys.argv[1:]
    else:
        args_list = list(argv)

    if not args_list:
        args_list = ["help"]

    TFFArgumentParser._current_argv = args_list
    parser = TFFArgumentParser(
        prog="tff",
        description=f"tff {__version__} - Run Transformation Fitness Function (tff) checks",
    )
    parser.add_argument(
        "--version",
        "-v",
        action="version",
        version=f"tff {__version__}",
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
        default="model",
        help="How to group violations in the report (default: model)",
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
    lint_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format to stdout",
    )
    lint_parser.add_argument(
        "--fix",
        action="store_true",
        help="Automatically fix simple linting violations if possible",
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
    health_parser.add_argument(
        "--scope",
        nargs="+",
        metavar="PATH_PREFIX",
        default=None,
        help=(
            "Restrict the health report to models whose path starts with one of the "
            "given prefixes (e.g. models/sources or models/marts/marketing)."
        ),
    )
    health_parser.add_argument(
        "--group-by",
        choices=["connascence", "domain"],
        default="connascence",
        dest="group_by",
        help="How to group the health breakdown (default: connascence)",
    )
    health_parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format to stdout",
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

    # Stats subcommand
    stats_parser = subparsers.add_parser(
        "stats",
        help="Show history and trends of fitness checks",
        description="Show history and trends of fitness checks",
    )
    stats_parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )
    stats_parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days of history to display (default: 7)",
    )
    stats_parser.add_argument(
        "--json",
        action="store_true",
        help="Output stats in JSON format to stdout",
    )

    # Docs subcommand
    docs_parser = subparsers.add_parser(
        "docs",
        help="Generate HTML documentation and health dashboard",
        description="Generate HTML documentation and health dashboard",
    )
    docs_parser.add_argument(
        "--project",
        type=Path,
        default=Path.cwd(),
        help="Project root directory (default: current directory)",
    )
    docs_parser.add_argument(
        "--config",
        default="fitness_functions.yaml",
        help="Path to fitness_functions.yaml (relative to project root)",
    )
    docs_parser.add_argument(
        "--provider",
        choices=["auto", "dbt", "sqlmesh"],
        default="auto",
        help="Pipeline engine provider (default: auto-detected)",
    )
    docs_parser.add_argument(
        "--dialect",
        default=None,
        help="SQL dialect of models (dbt only; auto-inferred by default)",
    )
    docs_parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output HTML path (default: project_root / tff_report.html)",
    )

    help_parser = subparsers.add_parser("help", help="Show help details for a command")
    help_parser.add_argument(
        "subcommand",
        nargs="?",
        choices=["lint", "health", "info", "stats", "docs"],
        help="Specific command to get help for",
    )

    args = parser.parse_args(args_list)

    if args.command == "help":
        if args.subcommand == "lint":
            lint_parser.print_help()
        elif args.subcommand == "health":
            health_parser.print_help()
        elif args.subcommand == "info":
            info_parser.print_help()
        elif args.subcommand == "stats":
            stats_parser.print_help()
        elif args.subcommand == "docs":
            docs_parser.print_help()
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
            " [cyan]████████╗[/cyan][green]███████╗███████╗[/green]\n"
            " [cyan]╚══██╔══╝[/cyan][green]██╔════╝██╔════╝[/green]\n"
            " [cyan]   ██║   [/cyan][green]█████╗  █████╗  [/green]\n"
            " [cyan]   ██║   [/cyan][green]██╔══╝  ██╔══╝  [/green]\n"
            " [cyan]   ██║   [/cyan][green]██║     ██║     [/green]\n"
            " [cyan]   ╚═╝   [/cyan][green]╚═╝     ╚═╝     [/green]"
        )
        console.print(logo)
        console.print()
        console.print("[bold cyan]● TFF Info[/bold cyan]")
        table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        table.add_column()
        table.add_column()

        table.add_row("  [bold]Project root:[/bold]", str(project_root))
        table.add_row("  [bold]Provider:[/bold]", provider)
        config_status = (
            "[green]found[/green]" if config_exists else "[red]missing[/red]"
        )
        table.add_row("  [bold]Config file:[/bold]", f"{args.config} ({config_status})")
        if config_exists:
            try:
                cfg = load_fitness_config(project_root, config_path)
                contract_path = resolve_project_path(cfg, cfg.contract_groups_path)
                exclusions_path = resolve_project_path(cfg, cfg.exclusions_path)
                contract_status = (
                    "[green]found[/green]"
                    if contract_path.exists()
                    else "[red]missing[/red]"
                )
                exclusions_status = (
                    "[green]found[/green]"
                    if exclusions_path.exists()
                    else "[red]missing[/red]"
                )
                table.add_row(
                    "  [bold]Contract groups:[/bold]",
                    f"{contract_path} ({contract_status})",
                )
                table.add_row(
                    "  [bold]Exclusions:[/bold]",
                    f"{exclusions_path} ({exclusions_status})",
                )
            except Exception as e:
                console.print(f"[yellow]Failed to load config: {e}[/yellow]")
        console.print(table)

        console.print("\n[bold cyan]● Adapter Versions[/bold cyan]")
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

        ver_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        ver_table.add_column()
        ver_table.add_column()

        def format_ver(pkg: str) -> str:
            ver = get_version(pkg)
            if ver == "not installed":
                return "[dim red]not installed[/dim red]"
            return f"[cyan]{ver}[/cyan]"

        tff_ver = format_ver("tff-core")
        ver_table.add_row("  [bold]tff-core[/bold]", tff_ver)

        import importlib.util

        has_sqlmesh = importlib.util.find_spec("sqlmesh") is not None

        sqlmesh_status = (
            f"{tff_ver} [dim](sqlmesh extra enabled)[/dim]"
            if has_sqlmesh
            else "[dim red]not enabled[/dim red] [dim](install using 'tff-core[sqlmesh]')[/dim]"
        )
        ver_table.add_row("  [bold]sqlmesh integration[/bold]", sqlmesh_status)
        ver_table.add_row(
            "  [bold]dbt integration[/bold]", f"{tff_ver} [dim](core)[/dim]"
        )
        console.print(ver_table)

        prov_table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
        prov_table.add_column()
        prov_table.add_column()

        if provider == "dbt":
            dbt_project = project_root / "dbt_project.yml"
            manifest = project_root / "target" / "manifest.json"
            dbt_project_status = (
                "[green]found[/green]" if dbt_project.exists() else "[red]missing[/red]"
            )
            manifest_status = (
                "[green]found[/green]" if manifest.exists() else "[red]missing[/red]"
            )
            prov_table.add_row(
                "  [bold]dbt_project.yml[/bold]",
                f"{dbt_project} ({dbt_project_status})",
            )
            prov_table.add_row(
                "  [bold]manifest.json[/bold]",
                f"{manifest} ({manifest_status})",
            )
        elif provider == "sqlmesh":
            config_py = project_root / "config.py"
            settings_yaml = project_root / "settings.yaml"
            config_py_status = (
                "[green]found[/green]" if config_py.exists() else "[red]missing[/red]"
            )
            settings_yaml_status = (
                "[green]found[/green]"
                if settings_yaml.exists()
                else "[red]missing[/red]"
            )
            prov_table.add_row(
                "  [bold]config.py[/bold]",
                f"{config_py} ({config_py_status})",
            )
            prov_table.add_row(
                "  [bold]settings.yaml[/bold]",
                f"{settings_yaml} ({settings_yaml_status})",
            )
        if prov_table.row_count > 0:
            console.print("\n[bold cyan]● Provider Files[/bold cyan]")
            console.print(prov_table)
        return 0

    if args.command == "stats":
        project_root = args.project.resolve()
        from tff.core.logs import collect_stats, render_ascii_chart
        from datetime import datetime
        import json

        history = collect_stats(project_root, args.days)
        if not history:
            print("No TFF run logs found under .tff_logs/.", file=sys.stderr)
            print(
                "Please run 'tff lint' or 'tff health' to generate reports first.",
                file=sys.stderr,
            )
            return 1

        if args.json:
            print(
                json.dumps(
                    {
                        "project_root": str(project_root),
                        "days": args.days,
                        "history": history,
                    },
                    indent=2,
                )
            )
            return 0

        # Output ASCII trend charts
        dates = [item["date"] for item in history]
        health_scores = [item["health_score"] for item in history]
        errors = [item["errors_count"] for item in history]
        warnings = [item["warnings_count"] for item in history]

        # 1. Health Score Trend
        from rich.console import Console

        console = Console()
        console.print("[bold cyan]● TFF Project Health Score Trend[/bold cyan]")
        has_health_data = any(h is not None for h in health_scores)
        if has_health_data:
            chart = render_ascii_chart(
                health_scores, dates, height=6, is_percentage=True
            )
            console.print(chart)
        else:
            console.print("  (No health score data in this timeframe)")
        console.print()

        # 2. Lint Violations Trend
        console.print(
            "[bold cyan]● TFF Lint Violations Trend (Errors & Warnings)[/bold cyan]"
        )
        has_lint_data = any(
            e is not None or w is not None for e, w in zip(errors, warnings)
        )
        if has_lint_data:
            total_violations = []
            for e, w in zip(errors, warnings):
                if e is None and w is None:
                    total_violations.append(None)
                else:
                    total_violations.append((e or 0) + (w or 0))
            chart = render_ascii_chart(
                total_violations, dates, height=6, is_percentage=False
            )
            console.print(chart)
        else:
            console.print("  (No lint violation data in this timeframe)")
        console.print()

        # 3. Summary Table
        from rich.table import Table
        from rich import box

        table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="bold cyan",
            padding=(0, 2, 0, 0),
        )
        table.add_column("Date", style="bold", no_wrap=True)
        table.add_column("Health Score", justify="right")
        table.add_column("Errors", justify="right")
        table.add_column("Warnings", justify="right")

        for item in history:
            try:
                dt = datetime.strptime(item["date"], "%Y-%m-%d")
                d_formatted = dt.strftime("%b %d")
            except Exception:
                d_formatted = item["date"]

            h_val = (
                f"{item['health_score']:.1f}%"
                if item["health_score"] is not None
                else "·"
            )
            e_val = (
                str(item["errors_count"]) if item["errors_count"] is not None else "·"
            )
            w_val = (
                str(item["warnings_count"])
                if item["warnings_count"] is not None
                else "·"
            )

            # Colorize output
            if item["health_score"] is not None:
                score = item["health_score"]
                color = "green" if score >= 90 else "yellow" if score >= 70 else "red"
                h_val = f"[{color}]{h_val}[/{color}]"

            if item["errors_count"] and item["errors_count"] > 0:
                e_val = f"[red]{e_val}[/red]"
            if item["warnings_count"] and item["warnings_count"] > 0:
                w_val = f"[yellow]{w_val}[/yellow]"

            table.add_row(d_formatted, h_val, e_val, w_val)

        console.print("[bold cyan]● Summary History[/bold cyan]")
        console.print(table)
        return 0

    if args.command == "docs":
        project_root = args.project.resolve()
        provider = args.provider
        if provider == "auto":
            try:
                provider = _detect_provider(project_root)
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                return 1

        from tff.core.docs import generate_docs_dashboard
        try:
            output_file = generate_docs_dashboard(
                project_root=project_root,
                output_path=args.output,
                provider=provider,
                dialect=args.dialect,
                config_path=args.config,
            )
            print(f"Successfully generated HTML dashboard at: {output_file}")
            return 0
        except Exception as e:
            print(f"Error generating dashboard: {e}", file=sys.stderr)
            return 1

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

        # Apply auto-fixes if --fix is set
        if args.command == "lint" and getattr(args, "fix", False) and findings:
            models = {}
            try:
                if provider == "dbt":
                    from tff.dbt.manifest import load_dbt_models
                    models = load_dbt_models(project_root, dialect=args.dialect)
                else:
                    from sqlmesh.core.context import Context
                    from tff.sqlmesh.loader import FitnessLoader
                    from tff.sqlmesh.runner import map_sqlmesh_context_models
                    context = Context(
                        paths=[str(project_root)],
                        loader=FitnessLoader,
                    )
                    models = map_sqlmesh_context_models(context)
            except Exception as e:
                print(f"Warning: Could not load models for autofix: {e}", file=sys.stderr)

            if models:
                from tff.core.autofix import apply_autofixes
                fix_logs = apply_autofixes(project_root, provider, findings, models)
                if fix_logs:
                    if not args.json:
                        from rich.console import Console
                        console = Console(stderr=True)
                        for log in fix_logs:
                            console.print(f"[green]✓[/green] {log}")
                    # Re-run checks to get the final state of the files
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
                            findings, models_checked, executed_checks = (
                                runner_module.run_all_checks(
                                    project_root=project_root,
                                    config=config,
                                    checks=checks,
                                )
                            )
                    except Exception as e:
                        print(f"Error executing checks after autofix: {e}", file=sys.stderr)
                        return 1

        if args.command == "lint":
            # 5. Render report
            from tff.core.logs import get_lint_json_data, save_log
            import json

            json_data = get_lint_json_data(findings, models_checked, args.fail_level)
            save_log(project_root, "lint", json_data)

            if args.json:
                print(json.dumps(json_data, indent=2))
                passed = json_data["passed"]
            else:
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
            from tff.core.logs import get_health_json_data, save_log
            import json

            scope: list[str] | None = getattr(args, "scope", None)
            group_by: str = getattr(args, "group_by", "connascence")

            scores = calculate_health_scores(
                findings, models_checked, config, provider, scope=scope
            )

            json_data = get_health_json_data(scores, models_checked)
            save_log(project_root, "health", json_data)

            if args.json:
                print(json.dumps(json_data, indent=2))
            else:
                render_health_report(scores, config, provider, group_by=group_by)

            overall_score = scores["overall_score"]
            if args.fail_under > 0.0 and overall_score < args.fail_under:
                if not args.json:
                    print(
                        f"Error: Project health score {overall_score:.1f}% is below threshold {args.fail_under:.1f}%",
                        file=sys.stderr,
                    )
                return 1
            return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
