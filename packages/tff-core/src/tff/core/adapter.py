"""Abstract PipelineAdapter interface and adapter registry."""

from __future__ import annotations

import importlib
import re
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Sequence

import yaml

from tff.core.exceptions import TffDependencyError, TffProviderError


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
        scoped_models: set[str] | None = None,
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
                raise TffDependencyError(
                    "dbt project detected, but tff is not installed with dbt support.",
                    hint='Please install it using: pip install "tff-core[dbt]" or uv add "tff-core[dbt]"',
                    provider="dbt",
                    package_hint="tff-core[dbt]",
                    original_error=e,
                ) from e
        elif provider == "sqlmesh":
            try:
                mod = importlib.import_module(module_name)
            except ImportError as e:
                raise TffDependencyError(
                    "SQLMesh project detected, but tff is not installed with sqlmesh support.",
                    hint='Please install it using: pip install "tff-core[sqlmesh]" or uv add "tff-core[sqlmesh]"',
                    provider="sqlmesh",
                    package_hint="tff-core[sqlmesh]",
                    original_error=e,
                ) from e
        elif provider == "dataform":
            try:
                mod = importlib.import_module(module_name)
            except ImportError as e:
                raise TffDependencyError(
                    "Dataform project detected, but tff is not installed with dataform support.",
                    hint='Please install it using: pip install "tff-core[dataform]" or uv add "tff-core[dataform]"',
                    provider="dataform",
                    package_hint="tff-core[dataform]",
                    original_error=e,
                ) from e
        else:
            mod = importlib.import_module(module_name)

        adapter_cls: type[PipelineAdapter] = getattr(mod, class_name)
        return adapter_cls()

    # 3. Check entry points
    ep_adapter = _load_adapter_from_entry_point(provider)
    if ep_adapter is not None:
        return ep_adapter

    raise TffProviderError(
        f"Unknown provider: {provider}",
        hint="Supported providers: dbt, sqlmesh, dataform",
        provider=provider,
    )


SQLMESH_YAML_KEYS: set[str] = {
    "gateways",
    "model_defaults",
    "default_gateway",
    "physical_schema",
    "gateway",
    "pinned_environments",
}


def _is_sqlmesh_python_config(path: Path, has_dbt_project: bool = False) -> bool:
    """Check if a config.py file is actually a SQLMesh configuration."""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    # Definite indicators: imports or references to sqlmesh
    if re.search(r"\b(import\s+sqlmesh|from\s+sqlmesh)\b", content):
        return True
    if "FitnessLoader" in content:
        return True

    # Check for Config( constructor
    if re.search(r"\bConfig\s*\(", content):
        # If a dbt_project.yml is present, avoid false positives from generic python config files
        # by requiring SQLMesh-specific terms.
        if has_dbt_project:
            sqlmesh_terms = (
                "gateways",
                "model_defaults",
                "default_gateway",
                "physical_schema",
                "sqlmesh",
                "DuckDBConnectionConfig",
                "Gateway",
            )
            return any(term in content for term in sqlmesh_terms)
        return True

    return False


def _is_sqlmesh_yaml_config(path: Path) -> bool:
    """Check if a config.yaml or config.yml file has characteristic SQLMesh top-level keys."""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        data = yaml.safe_load(content)
        if isinstance(data, dict):
            return any(k in data for k in SQLMESH_YAML_KEYS)
    except Exception:
        return False
    return False


def is_sqlmesh_project(project_root: Path, has_dbt_project: bool = False) -> bool:
    """Check if project_root contains SQLMesh configuration."""
    # 1. Unambiguous SQLMesh signature files or directories
    if (project_root / ".sqlmesh").exists():
        return True
    if (project_root / "sqlmesh.yaml").is_file() or (
        project_root / "sqlmesh.yml"
    ).is_file():
        return True

    # 2. Generic configuration files requiring content inspection
    config_py = project_root / "config.py"
    if config_py.is_file() and _is_sqlmesh_python_config(
        config_py, has_dbt_project=has_dbt_project
    ):
        return True

    for yaml_name in ("config.yaml", "config.yml"):
        config_yaml = project_root / yaml_name
        if config_yaml.is_file() and _is_sqlmesh_yaml_config(config_yaml):
            return True

    return False


def _detect_provider_from_models(project_root: Path) -> str | None:
    """Disambiguate or detect provider by inspecting files under models/."""
    models_dir = project_root / "models"
    if not models_dir.is_dir():
        return None

    sqlmesh_score = 0
    dbt_score = 0
    checked_files = 0
    max_files = 30

    candidate_files: list[Path] = []
    try:
        for ext in ("*.sql", "*.py"):
            candidate_files.extend(models_dir.rglob(ext))
    except OSError:
        return None

    for file_path in candidate_files:
        if not file_path.is_file():
            continue
        checked_files += 1
        if checked_files > max_files:
            break

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        # SQLMesh indicators: MODEL statement or @model decorator
        is_sqlmesh_model = bool(
            re.search(r"(?:^|\s)MODEL\s*\(", content, re.IGNORECASE)
            or re.search(r"@model\b", content)
            or re.search(r"\bfrom\s+sqlmesh\.core\.model\s+import\s+model\b", content)
        )

        # dbt indicators: Jinja config(), ref(), or source()
        is_dbt_model = bool(
            re.search(r"\{\{\s*(config|ref|source)\s*\(", content)
        )

        if is_sqlmesh_model and not is_dbt_model:
            sqlmesh_score += 1
        elif is_dbt_model and not is_sqlmesh_model:
            dbt_score += 1

    if sqlmesh_score > 0 and dbt_score == 0:
        return "sqlmesh"
    if dbt_score > 0 and sqlmesh_score == 0:
        return "dbt"
    return None


def _get_declared_provider(
    project_root: Path, config_path: str | Path | None = None
) -> str | None:
    """Read declared provider from fitness_functions.yaml or specified config path."""
    candidate_paths: list[Path] = []
    if config_path is not None:
        p = Path(config_path)
        candidate_paths.append(p if p.is_absolute() else project_root / p)
    else:
        candidate_paths.append(project_root / "fitness_functions.yaml")
        candidate_paths.append(project_root / "fitness_functions.yml")

    for path in candidate_paths:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
                data = yaml.safe_load(content)
                if isinstance(data, dict):
                    prov = data.get("provider")
                    if isinstance(prov, str):
                        prov = prov.strip().lower()
                        if prov and prov != "auto":
                            return prov
            except Exception:
                pass
    return None


def _detect_provider_single(
    project_root: Path, config_path: str | Path | None = None
) -> str:
    """Detect whether a single project root is dbt, SQLMesh, Dataform, or a custom registered adapter."""
    # 0. Check for explicitly declared provider in fitness_functions.yaml
    declared = _get_declared_provider(project_root, config_path=config_path)
    if declared is not None:
        return declared

    # Check for dbt signature file
    is_dbt = (project_root / "dbt_project.yml").exists()

    # Check for SQLMesh signature files (with asymmetric dbt awareness)
    is_sqlmesh = is_sqlmesh_project(project_root, has_dbt_project=is_dbt)

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
        model_prov = _detect_provider_from_models(project_root)
        if model_prov in ("dbt", "sqlmesh"):
            return model_prov
        raise TffProviderError(
            f"Both dbt and SQLMesh configuration files were detected in the project root ({project_root}).",
            hint="Please specify the provider explicitly using the --provider option (e.g. '--provider dbt' or '--provider sqlmesh').",
            project_root=project_root,
        )
    if len(detected) > 1:
        names = ", ".join(detected)
        raise TffProviderError(
            f"Multiple pipeline configuration files were detected in the project root {project_root} ({names}).",
            hint="Please specify the provider explicitly using the --provider option (e.g. '--provider dbt', '--provider sqlmesh', or '--provider dataform').",
            project_root=project_root,
        )
    if len(detected) == 1:
        return detected[0]

    # Fallback to model syntax inspection when no configuration files were detected
    model_prov = _detect_provider_from_models(project_root)
    if model_prov is not None:
        return model_prov

    raise TffProviderError(
        f"Could not detect project type for {project_root} (neither dbt_project.yml, SQLMesh config, nor Dataform config was found).",
        hint="Please run this command from your project root, or specify the provider explicitly using the --provider option.",
        project_root=project_root,
    )


def detect_provider(
    project_root: Path | Sequence[Path], config_path: str | Path | None = None
) -> str:
    """Detect whether a project root (or set of project roots) is dbt, SQLMesh, Dataform, or a custom registered adapter."""
    roots = normalize_project_roots(project_root)
    if not roots:
        return _detect_provider_single(Path.cwd(), config_path=config_path)

    providers = [_detect_provider_single(r, config_path=config_path) for r in roots]
    unique_providers = list(dict.fromkeys(providers))
    if len(unique_providers) > 1:
        names = ", ".join(unique_providers)
        raise TffProviderError(
            f"Conflicting pipeline engine providers detected across project roots ({names}).",
            hint="Please ensure all project roots use the same pipeline engine or specify --provider explicitly.",
            project_root=roots,
        )
    return unique_providers[0]
