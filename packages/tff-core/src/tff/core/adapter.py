"""Abstract PipelineAdapter interface and adapter registry."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence


def normalize_project_roots(project_root: Path | Sequence[Path | str] | str) -> list[Path]:
    """Normalize a single Path or a sequence of paths into a list of unique, resolved Path objects."""
    if isinstance(project_root, (str, Path)):
        return [Path(project_root).resolve()]
    return list(dict.fromkeys(Path(p).resolve() for p in project_root))


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
        project_root: Path | Sequence[Path],
        dialect: str | None = None,
        manifest_path: str | Path | None = None,
    ) -> dict[str, ModelRepresentation]:
        """Load and map models from the pipeline project into ModelRepresentation objects."""
        raise NotImplementedError

    @abstractmethod
    def run_checks(
        self,
        project_root: Path | Sequence[Path],
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

    def get_diagnostic_files(
        self, project_root: Path | Sequence[Path]
    ) -> list[tuple[str, str]]:
        """Return list of (file_label, display_status_str) for diagnostics."""
        return []


ADAPTER_CLASSES: dict[str, tuple[str, str]] = {
    "dbt": ("tff.dbt.adapter", "DBTAdapter"),
    "sqlmesh": ("tff.sqlmesh.adapter", "SQLMeshAdapter"),
    "dataform": ("tff.dataform.adapter", "DataformAdapter"),
}

_REGISTERED_ADAPTERS: dict[
    str,
    type[PipelineAdapter] | PipelineAdapter | Callable[[], PipelineAdapter],
] = {}


def register_adapter(
    provider: str,
    adapter_cls_or_factory: (
        type[PipelineAdapter] | PipelineAdapter | Callable[[], PipelineAdapter]
    ),
) -> None:
    """Register an adapter class, instance, or factory under a provider name."""
    _REGISTERED_ADAPTERS[provider] = adapter_cls_or_factory


def _load_adapter_from_entry_point(provider: str) -> PipelineAdapter | None:
    """Attempt to load an adapter registered via 'tff.adapters' entry points."""
    import importlib.metadata as metadata

    try:
        eps = metadata.entry_points(group="tff.adapters")
    except Exception:
        return None

    for ep in eps:
        if ep.name == provider:
            try:
                loaded = ep.load()
            except Exception as e:
                raise ImportError(f"Failed to load adapter plugin '{provider}': {e}") from e

            if isinstance(loaded, type) and issubclass(loaded, PipelineAdapter):
                return loaded()
            if isinstance(loaded, PipelineAdapter):
                return loaded
            if callable(loaded):
                res = loaded()
                if isinstance(res, PipelineAdapter):
                    return res
            raise TypeError(
                f"Adapter entry point '{provider}' did not resolve to a PipelineAdapter class or instance."
            )
    return None


def get_available_providers() -> list[str]:
    """Return all available adapter provider identifiers."""
    import importlib.metadata as metadata

    providers = set(ADAPTER_CLASSES.keys())
    providers.update(_REGISTERED_ADAPTERS.keys())
    try:
        eps = metadata.entry_points(group="tff.adapters")
        for ep in eps:
            providers.add(ep.name)
    except Exception:
        pass
    return sorted(providers)


def get_adapter(provider: str) -> PipelineAdapter:
    """Load and return the adapter instance for the specified provider."""
    # 1. Check custom registered adapters
    if provider in _REGISTERED_ADAPTERS:
        item = _REGISTERED_ADAPTERS[provider]
        if isinstance(item, type) and issubclass(item, PipelineAdapter):
            return item()
        if isinstance(item, PipelineAdapter):
            return item
        if callable(item):
            res = item()
            if isinstance(res, PipelineAdapter):
                return res
            raise TypeError(
                f"Adapter factory for '{provider}' did not return a PipelineAdapter instance."
            )

    # 2. Check built-in and configured module/class pairs
    if provider in ADAPTER_CLASSES:
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

    # 3. Check entry points
    ep_adapter = _load_adapter_from_entry_point(provider)
    if ep_adapter is not None:
        return ep_adapter

    raise ValueError(f"Unknown provider: {provider}")


def _detect_provider_single(project_root: Path) -> str:
    """Detect whether a single project root is dbt, SQLMesh, Dataform, or a custom registered adapter."""
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

    # Check registered or entry-point adapters
    for prov in get_available_providers():
        if prov in ("dbt", "sqlmesh", "dataform"):
            continue
        try:
            adapter = get_adapter(prov)
            if adapter.is_applicable(project_root):
                if prov not in detected:
                    detected.append(prov)
        except Exception:
            continue

    if is_dbt and is_sqlmesh and not is_dataform and len(detected) == 2:
        raise ValueError(
            f"Both dbt and SQLMesh configuration files were detected in the project root ({project_root}).\n"
            "Please specify the provider explicitly using the --provider option (e.g. '--provider dbt' or '--provider sqlmesh')."
        )
    if len(detected) > 1:
        names = ", ".join(detected)
        raise ValueError(
            f"Multiple pipeline configuration files were detected in the project root {project_root} ({names}).\n"
            f"Please specify the provider explicitly using the --provider option (e.g. '--provider dbt', '--provider sqlmesh', or '--provider dataform')."
        )
    if len(detected) == 1:
        return detected[0]

    raise ValueError(
        f"Could not detect project type for {project_root} (neither dbt_project.yml, SQLMesh config, nor Dataform config was found).\n"
        "Please run this command from your project root, or specify the provider explicitly using the --provider option."
    )


def detect_provider(project_root: Path | Sequence[Path]) -> str:
    """Detect whether a project root (or set of project roots) is dbt, SQLMesh, Dataform, or a custom registered adapter."""
    roots = normalize_project_roots(project_root)
    if not roots:
        return _detect_provider_single(Path.cwd())

    providers = [_detect_provider_single(r) for r in roots]
    unique_providers = list(dict.fromkeys(providers))
    if len(unique_providers) > 1:
        names = ", ".join(unique_providers)
        raise ValueError(
            f"Conflicting pipeline engine providers detected across project roots ({names}).\n"
            "Please ensure all project roots use the same pipeline engine or specify --provider explicitly."
        )
    return unique_providers[0]
