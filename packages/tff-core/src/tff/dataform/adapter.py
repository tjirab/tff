"""Dataform adapter implementation for tff."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from tff.core.adapter import PipelineAdapter, normalize_project_roots

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
        project_root: Path | Sequence[Path],
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        from tff.dataform.manifest import load_dataform_models

        roots = normalize_project_roots(project_root)
        return load_dataform_models(
            project_root=roots[0],
            manifest_path=manifest_path,
            dialect=dialect,
        )

    def run_checks(
        self,
        project_root: Path | Sequence[Path],
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
        models: dict[str, ModelRepresentation] | None = None,
    ) -> tuple[list[LintFinding], int, list[str]]:
        from tff.dataform.runner import run_all_checks

        roots = normalize_project_roots(project_root)
        return run_all_checks(
            project_root=roots[0],
            config=config,
            checks=checks,
            dialect=dialect,
            manifest_path=manifest_path,
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
        from tff.core.autofix import fix_dataform_metadata

        return fix_dataform_metadata(
            abs_path=abs_path,
            missing_owner=missing_owner,
            missing_description=missing_description,
            model_name=model_name,
        )

    def get_diagnostic_files(
        self, project_root: Path | Sequence[Path]
    ) -> list[tuple[str, str]]:
        from tff.dataform.manifest import _find_manifest_file

        roots = normalize_project_roots(project_root)
        rows: list[tuple[str, str]] = []
        for root in roots:
            prefix = f"[{root.name}] " if len(roots) > 1 else ""
            ws_yaml = root / "workflow_settings.yaml"
            df_json = root / "dataform.json"

            found_manifest = _find_manifest_file(root)
            m_status = (
                f"[green]{found_manifest.name}[/green]"
                if found_manifest
                else "[dim]not found (will compile via CLI or parse .sqlx)[/dim]"
            )

            if ws_yaml.exists():
                rows.append((f"{prefix}workflow_settings.yaml", f"{ws_yaml} ([green]found[/green])"))
            elif df_json.exists():
                rows.append((f"{prefix}dataform.json", f"{df_json} ([green]found[/green])"))
            else:
                rows.append((f"{prefix}workflow_settings.yaml", "[red]missing[/red]"))

            rows.append((f"{prefix}compilation manifest", m_status))
        return rows
