"""dbt adapter implementation for tff."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from tff.core.adapter import PipelineAdapter, normalize_project_roots

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding


class DBTAdapter(PipelineAdapter):
    """Pipeline adapter for dbt projects."""

    @property
    def provider_name(self) -> str:
        return "dbt"

    def is_applicable(self, project_root: Path) -> bool:
        return (project_root / "dbt_project.yml").exists()

    def load_models(
        self,
        project_root: Path | Sequence[Path],
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        from tff.dbt.manifest import load_dbt_models

        roots = normalize_project_roots(project_root)
        return load_dbt_models(roots[0], dialect=dialect)

    def run_checks(
        self,
        project_root: Path | Sequence[Path],
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
        models: dict[str, ModelRepresentation] | None = None,
    ) -> tuple[list[LintFinding], int, list[str]]:
        from tff.dbt.runner import run_all_checks

        roots = normalize_project_roots(project_root)
        return run_all_checks(
            project_root=roots[0],
            config=config,
            checks=checks,
            dialect=dialect,
            models=models,
        )

    def apply_metadata_fix(
        self,
        project_root: Path,
        abs_path: Path,
        model_name: str,
        missing_owner: bool,
        missing_description: bool,
    ) -> str | None:
        from tff.core.autofix import fix_dbt_metadata

        return fix_dbt_metadata(
            abs_path=abs_path,
            model_name=model_name,
            missing_owner=missing_owner,
            missing_description=missing_description,
        )

    def get_diagnostic_files(
        self, project_root: Path | Sequence[Path]
    ) -> list[tuple[str, str]]:
        roots = normalize_project_roots(project_root)
        results: list[tuple[str, str]] = []
        for root in roots:
            prefix = f"[{root.name}] " if len(roots) > 1 else ""
            dbt_project = root / "dbt_project.yml"
            manifest = root / "target" / "manifest.json"
            dbt_project_status = (
                "[green]found[/green]" if dbt_project.exists() else "[red]missing[/red]"
            )
            manifest_status = (
                "[green]found[/green]" if manifest.exists() else "[red]missing[/red]"
            )
            results.append((f"{prefix}dbt_project.yml", f"{dbt_project} ({dbt_project_status})"))
            results.append((f"{prefix}manifest.json", f"{manifest} ({manifest_status})"))
        return results
