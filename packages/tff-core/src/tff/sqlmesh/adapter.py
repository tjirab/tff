"""SQLMesh adapter implementation for tff."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from tff.core.adapter import PipelineAdapter, normalize_project_roots

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding


class SQLMeshAdapter(PipelineAdapter):
    """Pipeline adapter for SQLMesh projects."""

    @property
    def provider_name(self) -> str:
        return "sqlmesh"

    def is_applicable(self, project_root: Path) -> bool:
        return (
            (project_root / ".sqlmesh").exists()
            or (project_root / "config.py").exists()
            or (project_root / "config.yaml").exists()
            or (project_root / "config.yml").exists()
        )

    def load_models(
        self,
        project_root: Path | Sequence[Path],
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        from sqlmesh.core.context import Context
        from tff.sqlmesh.loader import FitnessLoader
        from tff.sqlmesh.runner import map_sqlmesh_context_models

        roots = normalize_project_roots(project_root)
        context = Context(
            paths=[str(r) for r in roots],
            loader=FitnessLoader,
        )
        return map_sqlmesh_context_models(context)

    def run_checks(
        self,
        project_root: Path | Sequence[Path],
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
        models: dict[str, ModelRepresentation] | None = None,
    ) -> tuple[list[LintFinding], int, list[str]]:
        from tff.sqlmesh.runner import run_all_checks

        return run_all_checks(
            project_root=project_root,
            config=config,
            checks=checks,
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
        from tff.core.autofix import fix_sqlmesh_metadata

        return fix_sqlmesh_metadata(
            abs_path=abs_path,
            missing_owner=missing_owner,
            missing_description=missing_description,
        )

    def get_diagnostic_files(
        self, project_root: Path | Sequence[Path]
    ) -> list[tuple[str, str]]:
        roots = normalize_project_roots(project_root)
        rows: list[tuple[str, str]] = []
        for root in roots:
            prefix = f"[{root.name}] " if len(roots) > 1 else ""
            config_py = root / "config.py"
            settings_yaml = root / "settings.yaml"
            config_py_status = (
                "[green]found[/green]" if config_py.exists() else "[red]missing[/red]"
            )
            settings_yaml_status = (
                "[green]found[/green]"
                if settings_yaml.exists()
                else "[red]missing[/red]"
            )
            rows.append((f"{prefix}config.py", f"{config_py} ({config_py_status})"))
            rows.append((f"{prefix}settings.yaml", f"{settings_yaml} ({settings_yaml_status})"))
        return rows
