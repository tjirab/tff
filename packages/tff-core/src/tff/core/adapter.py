"""Abstract PipelineAdapter interface and adapter registry."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding


class PipelineAdapter(ABC):
    """Abstract interface for transformation pipeline engine adapters."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """The identifier string for this provider, e.g. 'dbt', 'sqlmesh', 'dataform'."""
        raise NotImplementedError

    @abstractmethod
    def is_applicable(self, project_root: Path) -> bool:
        """Return True if project_root contains this adapter's configuration."""
        raise NotImplementedError

    @abstractmethod
    def load_models(
        self,
        project_root: Path,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        """Load and map models from the pipeline project into ModelRepresentation objects."""
        raise NotImplementedError

    @abstractmethod
    def run_checks(
        self,
        project_root: Path,
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
        models: dict[str, ModelRepresentation] | None = None,
    ) -> tuple[list[LintFinding], int, list[str]]:
        """Run all enabled fitness functions and linter checks."""
        raise NotImplementedError

    def apply_metadata_fix(
        self,
        project_root: Path,
        abs_path: Path,
        model_name: str,
        missing_owner: bool,
        missing_description: bool,
    ) -> str | None:
        """Apply metadata fixes (owner, description) to model definition file if supported."""
        return None

    def get_diagnostic_files(self, project_root: Path) -> list[tuple[str, str]]:
        """Return list of (file_label, display_status_str) for diagnostics."""
        return []


ADAPTER_CLASSES: dict[str, tuple[str, str]] = {
    "dbt": ("tff.dbt.adapter", "DBTAdapter"),
    "sqlmesh": ("tff.sqlmesh.adapter", "SQLMeshAdapter"),
    "dataform": ("tff.dataform.adapter", "DataformAdapter"),
}


def get_adapter(provider: str) -> PipelineAdapter:
    """Load and return the adapter instance for the specified provider."""
    if provider not in ADAPTER_CLASSES:
        raise ValueError(f"Unknown provider: {provider}")

    module_name, class_name = ADAPTER_CLASSES[provider]

    if provider == "dbt":
        try:
            mod = importlib.import_module(module_name)
        except ImportError as e:
            raise ImportError(
                "dbt project detected, but tff is not installed with dbt support.\n"
                'Please install it using: pip install "tff-core[dbt]" or uv add "tff-core[dbt]"'
            ) from e
    elif provider == "sqlmesh":
        try:
            mod = importlib.import_module(module_name)
        except ImportError as e:
            raise ImportError(
                "SQLMesh project detected, but tff is not installed with sqlmesh support.\n"
                'Please install it using: pip install "tff-core[sqlmesh]" or uv add "tff-core[sqlmesh]"'
            ) from e
    elif provider == "dataform":
        try:
            mod = importlib.import_module(module_name)
        except ImportError as e:
            raise ImportError(
                "Dataform project detected, but tff is not installed with dataform support.\n"
                'Please install it using: pip install "tff-core[dataform]" or uv add "tff-core[dataform]"'
            ) from e
    else:
        mod = importlib.import_module(module_name)

    adapter_cls: type[PipelineAdapter] = getattr(mod, class_name)
    return adapter_cls()


def detect_provider(project_root: Path) -> str:
    """Detect whether a project is dbt, SQLMesh, or Dataform."""
    # Check for dbt signature file
    is_dbt = (project_root / "dbt_project.yml").exists()

    # Check for SQLMesh signature files
    is_sqlmesh = (
        (project_root / ".sqlmesh").exists()
        or (project_root / "config.py").exists()
        or (project_root / "config.yaml").exists()
        or (project_root / "config.yml").exists()
    )

    # Check for Dataform signature files
    is_dataform = (project_root / "workflow_settings.yaml").exists() or (
        project_root / "dataform.json"
    ).exists()

    detected = [
        p
        for p, found in [
            ("dbt", is_dbt),
            ("sqlmesh", is_sqlmesh),
            ("dataform", is_dataform),
        ]
        if found
    ]

    if is_dbt and is_sqlmesh and not is_dataform:
        raise ValueError(
            "Both dbt and SQLMesh configuration files were detected in the project root.\n"
            "Please specify the provider explicitly using the --provider option (e.g. '--provider dbt' or '--provider sqlmesh')."
        )
    if len(detected) > 1:
        names = ", ".join(detected)
        raise ValueError(
            f"Multiple pipeline configuration files were detected in the project root ({names}).\n"
            f"Please specify the provider explicitly using the --provider option (e.g. '--provider dbt', '--provider sqlmesh', or '--provider dataform')."
        )
    if is_dbt:
        return "dbt"
    if is_sqlmesh:
        return "sqlmesh"
    if is_dataform:
        return "dataform"

    raise ValueError(
        "Could not detect project type (neither dbt_project.yml, SQLMesh config, nor Dataform config was found).\n"
        "Please run this command from your project root, or specify the provider explicitly using the --provider option."
    )
