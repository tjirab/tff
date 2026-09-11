"""Dataform adapter implementation for TFF."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from tff.core.adapter import PipelineAdapter

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding


class DataformAdapter(PipelineAdapter):
    """Pipeline adapter for Dataform projects."""

    @property
    def provider_name(self) -> str:
        return "dataform"

    def is_applicable(self, project_root: Path) -> bool:
        return (project_root / "workflow_settings.yaml").exists() or (
            project_root / "dataform.json"
        ).exists()

    def load_models(
        self,
        project_root: Path,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        from tff.dataform.manifest import load_dataform_models

        return load_dataform_models(
            project_root=project_root,
            manifest_path=manifest_path,
            dialect=dialect,
        )

    def run_checks(
        self,
        project_root: Path,
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
        models: dict[str, ModelRepresentation] | None = None,
    ) -> tuple[list[LintFinding], int, list[str]]:
        from tff.dataform.runner import run_all_checks

        return run_all_checks(
            project_root=project_root,
            config=config,
            checks=checks,
            dialect=dialect,
            manifest_path=manifest_path,
            models=models,
        )

    def get_diagnostic_files(self, project_root: Path) -> list[tuple[str, str]]:
        ws_yaml = project_root / "workflow_settings.yaml"
        df_json = project_root / "dataform.json"
        from tff.dataform.manifest import _find_manifest_file

        found_manifest = _find_manifest_file(project_root)
        m_status = (
            f"[green]{found_manifest.name}[/green]"
            if found_manifest
            else "[dim]not found (will compile via CLI or parse .sqlx)[/dim]"
        )

        rows: list[tuple[str, str]] = []
        if ws_yaml.exists():
            rows.append(("workflow_settings.yaml", f"{ws_yaml} ([green]found[/green])"))
        elif df_json.exists():
            rows.append(("dataform.json", f"{df_json} ([green]found[/green])"))
        else:
            rows.append(("workflow_settings.yaml", "[red]missing[/red]"))

        rows.append(("compilation manifest", m_status))
        return rows
