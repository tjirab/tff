"""dbt adapter implementation for TFF."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tff.core.adapter import PipelineAdapter

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
        project_root: Path,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        from tff.dbt.manifest import load_dbt_models

        return load_dbt_models(project_root, dialect=dialect)

    def run_checks(
        self,
        project_root: Path,
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
        models: dict[str, ModelRepresentation] | None = None,
    ) -> tuple[list[LintFinding], int, list[str]]:
        from tff.dbt.runner import run_all_checks

        return run_all_checks(
            project_root=project_root,
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

    def get_diagnostic_files(self, project_root: Path) -> list[tuple[str, str]]:
        dbt_project = project_root / "dbt_project.yml"
        manifest = project_root / "target" / "manifest.json"
        dbt_project_status = (
            "[green]found[/green]" if dbt_project.exists() else "[red]missing[/red]"
        )
        manifest_status = (
            "[green]found[/green]" if manifest.exists() else "[red]missing[/red]"
        )
        return [
            (
                "dbt_project.yml",
                f"{dbt_project} ({dbt_project_status})",
            ),
            (
                "manifest.json",
                f"{manifest} ({manifest_status})",
            ),
        ]
