"""Plugin discovery and dynamic loader for custom rules and adapters."""

from __future__ import annotations

import importlib
import importlib.metadata as metadata
import importlib.util
import inspect
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from tff.core.adapter import PipelineAdapter
    from tff.core.registry import CheckDefinition, CheckRegistry

logger = logging.getLogger(__name__)


def discover_rule_entry_points(
    registry: CheckRegistry | None = None,
    raise_errors: bool = False,
) -> list[CheckDefinition]:
    """Discover and register rules from the 'tff.rules' entry point group."""
    if registry is None:
        from tff.core.registry import registry as default_registry

        registry = default_registry

    from tff.core.registry import CheckDefinition as CheckDef
    from tff.core.rules.base import Rule

    try:
        eps = metadata.entry_points(group="tff.rules")
    except Exception as e:
        logger.debug("Error querying 'tff.rules' entry points: %s", e)
        return []

    discovered: list[CheckDefinition] = []
    for ep in eps:
        try:
            target = ep.load()
            if isinstance(target, type) and issubclass(target, Rule) and target is not Rule:
                check_def = registry.register_rule(target, id=ep.name)
                discovered.append(check_def)
            elif isinstance(target, CheckDef):
                registry.register(target)
                discovered.append(target)
            elif callable(target):
                res = target(registry)
                if isinstance(res, CheckDef):
                    registry.register(res)
                    discovered.append(res)
                elif isinstance(res, list):
                    for item in res:
                        if isinstance(item, CheckDef):
                            registry.register(item)
                            discovered.append(item)
        except Exception as e:
            logger.warning("Failed to load rule entry point '%s': %s", ep.name, e)
            if raise_errors:
                raise
    return discovered


def discover_adapter_entry_points(
    raise_errors: bool = False,
) -> dict[str, type[PipelineAdapter] | PipelineAdapter | Callable[[], PipelineAdapter]]:
    """Discover and register pipeline adapters from the 'tff.adapters' entry point group."""
    from tff.core.adapter import register_adapter

    try:
        eps = metadata.entry_points(group="tff.adapters")
    except Exception as e:
        logger.debug("Error querying 'tff.adapters' entry points: %s", e)
        return {}

    discovered: dict[str, Any] = {}
    for ep in eps:
        try:
            target = ep.load()
            register_adapter(ep.name, target)
            discovered[ep.name] = target
        except Exception as e:
            logger.warning("Failed to load adapter entry point '%s': %s", ep.name, e)
            if raise_errors:
                raise
    return discovered


def extract_and_register_from_module(
    module: Any,
    registry: CheckRegistry,
) -> list[CheckDefinition]:
    """Scan an imported module for rules, adapters, and registration hooks."""
    from tff.core.adapter import PipelineAdapter, register_adapter
    from tff.core.registry import CheckDefinition as CheckDef
    from tff.core.rules.base import Rule

    registered: list[CheckDefinition] = []

    # 1. Check for explicit rule registration hook
    hook_fn = getattr(module, "register", None) or getattr(module, "register_rules", None)
    if callable(hook_fn):
        res = hook_fn(registry)
        items = [res] if isinstance(res, CheckDef) else (res if isinstance(res, list) else [])
        for item in items:
            if isinstance(item, CheckDef):
                registry.register(item)
                registered.append(item)

    # 2. Check for explicit adapter registration hook
    if hasattr(module, "register_adapters") and callable(module.register_adapters):
        module.register_adapters()

    # 3. Auto-discover Rule and PipelineAdapter classes defined in the module
    for _, obj in inspect.getmembers(module, inspect.isclass):
        if issubclass(obj, Rule) and obj is not Rule:
            is_builtin = obj.__module__.startswith("tff.core.rules") or obj.__module__.startswith("tff.core.checks")
            if not is_builtin and (
                obj.__module__ == getattr(module, "__name__", "")
                or getattr(obj, "__tff_plugin__", False)
                or getattr(module, obj.__name__, None) is obj
            ):
                check_def = registry.register_rule(obj)
                if check_def not in registered:
                    registered.append(check_def)

        if issubclass(obj, PipelineAdapter) and obj is not PipelineAdapter:
            is_builtin_adapter = (
                obj.__module__.startswith("tff.dbt")
                or obj.__module__.startswith("tff.sqlmesh")
                or obj.__module__.startswith("tff.dataform")
                or obj.__module__.startswith("tff.core")
            )
            if not is_builtin_adapter and (
                obj.__module__ == getattr(module, "__name__", "")
                or getattr(obj, "__tff_plugin__", False)
                or getattr(module, obj.__name__, None) is obj
            ):
                provider_prop = getattr(obj, "provider_name", None)
                if isinstance(provider_prop, property) or provider_prop is None:
                    try:
                        provider_name = obj().provider_name
                    except Exception:
                        provider_name = obj.__name__.lower().removesuffix("adapter")
                else:
                    provider_name = str(provider_prop)
                register_adapter(provider_name, obj)


    # 4. Auto-discover CheckDefinition instances defined in the module
    for _, obj in inspect.getmembers(module):
        if isinstance(obj, CheckDef):
            registry.register(obj)
            if obj not in registered:
                registered.append(obj)

    return registered


def load_plugin_module_or_file(
    path_or_module: str | Path,
    project_root: Path | None = None,
    registry: CheckRegistry | None = None,
) -> list[CheckDefinition]:
    """Load a plugin from a Python file path or importable module name."""
    if registry is None:
        from tff.core.registry import registry as default_registry

        registry = default_registry

    raw_str = str(path_or_module)
    is_path_like = (
        isinstance(path_or_module, Path)
        or raw_str.endswith(".py")
        or "/" in raw_str
        or "\\" in raw_str
    )

    if is_path_like:
        path = Path(path_or_module)
        if not path.is_absolute():
            path = (project_root or Path.cwd()) / path

        if not path.exists():
            raise FileNotFoundError(f"Plugin file not found: {path}")
        if not path.is_file():
            raise ValueError(f"Plugin path is not a file: {path}")

        module_name = f"_tff_plugin_{path.stem}_{abs(hash(str(path.resolve())))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Could not load module specification from {path}")

        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    else:
        try:
            module = importlib.import_module(raw_str)
        except ImportError as e:
            # Check if there is a local file matching without .py extension
            local_candidate = (project_root or Path.cwd()) / raw_str
            if local_candidate.with_suffix(".py").exists():
                return load_plugin_module_or_file(
                    local_candidate.with_suffix(".py"),
                    project_root=project_root,
                    registry=registry,
                )
            raise ImportError(
                f"Failed to import plugin module '{raw_str}': {e}"
            ) from e

    return extract_and_register_from_module(module, registry)


def load_plugins(
    plugins: list[str | Path],
    project_root: Path | None = None,
    registry: CheckRegistry | None = None,
) -> list[CheckDefinition]:
    """Load a collection of plugins and return all registered check definitions."""
    if registry is None:
        from tff.core.registry import registry as default_registry

        registry = default_registry

    all_registered: list[CheckDefinition] = []
    for plugin in plugins:
        # Avoid reloading the same plugin into the registry if already loaded
        canonical_key = str(plugin)
        if canonical_key in registry._loaded_plugins:
            continue
        registry._loaded_plugins.add(canonical_key)
        newly_registered = load_plugin_module_or_file(
            plugin,
            project_root=project_root,
            registry=registry,
        )
        all_registered.extend(newly_registered)
    return all_registered
