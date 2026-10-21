"""Path helpers for layer and domain resolution."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence

from tff.core.config import DEFAULT_LAYER_ORDER


def get_relative_path(
    file_path: str | Path,
    project_root: Path | Sequence[Path] | None = None,
) -> str:
    """Normalize file path to a relative path with forward slashes."""
    path_obj = Path(file_path)
    if project_root is not None:
        roots = [project_root] if isinstance(project_root, Path) else list(project_root)
        for r in roots:
            try:
                if path_obj.is_absolute():
                    rel = path_obj.relative_to(r.resolve())
                else:
                    rel = path_obj
                return str(rel).replace("\\", "/")
            except ValueError:
                pass
    try:
        if path_obj.is_absolute():
            rel = path_obj.relative_to(Path.cwd().resolve())
            return str(rel).replace("\\", "/")
    except ValueError:
        pass
    return str(path_obj).replace("\\", "/")


def is_finding_in_files(
    finding: dict[str, Any] | Any,
    modified_files: set[str],
    project_root: Path | Sequence[Path] | None = None,
    repo_root: Path | None = None,
) -> bool:
    """Check whether a finding belongs to one of the modified files."""
    if not modified_files:
        return False

    if isinstance(finding, dict):
        raw_path = finding.get("path")
        model = finding.get("model")
    else:
        raw_path = getattr(finding, "path", None)
        model = getattr(finding, "model", None)

    path_str = str(raw_path or "").replace("\\", "/")
    roots = (
        [project_root]
        if isinstance(project_root, Path)
        else list(project_root)
        if project_root is not None
        else []
    )
    rel_proj_strs = (
        [get_relative_path(path_str, r) for r in roots]
        if (path_str and roots)
        else ([path_str] if path_str else [])
    )

    for mf in modified_files:
        norm_mf = mf.replace("\\", "/")
        for candidate in (path_str, *rel_proj_strs):
            if candidate and (norm_mf == candidate or norm_mf.endswith(f"/{candidate}")):
                return True
        if model and Path(norm_mf).stem == model:
            return True
    return False



def _find_base_index(parts: tuple[str, ...]) -> int:
    for base in ("models", "definitions"):
        if base in parts:
            return parts.index(base)
    raise ValueError("Neither 'models' nor 'definitions' found in path")


def get_layer_from_path(path: str, layer_order: list[str] | None = None) -> str | None:
    parts = Path(path).parts
    try:
        models_index = _find_base_index(parts)
        if layer_order is None:
            layer_order = DEFAULT_LAYER_ORDER

        if layer_order:
            for part in parts[models_index + 1:]:
                if part in layer_order:
                    return part

        return parts[models_index + 1]
    except (ValueError, IndexError):
        return None


def get_marts_domain_from_path(path: str, layer_name: str = "marts") -> str | None:
    parts = Path(path).parts
    try:
        models_index = _find_base_index(parts)
        layer_index = None
        for i, part in enumerate(parts[models_index + 1:], start=models_index + 1):
            if part == layer_name:
                layer_index = i
                break

        if layer_index is None:
            return None

        if layer_index == models_index + 1:
            return parts[models_index + 2]
        else:
            return parts[models_index + 1]
    except (ValueError, IndexError):
        return None


def get_layer_and_domain(
    path: str, layer_order: list[str] | None = None
) -> tuple[str | None, str | None]:
    parts = Path(path).parts
    try:
        models_index = _find_base_index(parts)
        if layer_order is None:
            layer_order = DEFAULT_LAYER_ORDER

        layer = None
        layer_index = None
        if layer_order:
            for i, part in enumerate(parts[models_index + 1:], start=models_index + 1):
                if part in layer_order:
                    layer = part
                    layer_index = i
                    break

        if layer is None:
            layer = parts[models_index + 1]
            layer_index = models_index + 1

        if layer_index == models_index + 1:
            if len(parts) > models_index + 2:
                domain = parts[models_index + 2]
            else:
                domain = None
        else:
            domain = parts[models_index + 1]

        if domain:
            for ext in (".sql", ".sqlx"):
                if domain.endswith(ext):
                    domain = domain[:-len(ext)]
                    break

        return layer, domain
    except (ValueError, IndexError):
        return None, None


def model_path_relative(model) -> str | None:
    if isinstance(model, dict):
        path = model.get("path") or model.get("_path")
    elif isinstance(model, (str, Path)):
        path = str(model)
    else:
        path = getattr(model, "path", getattr(model, "_path", None))
    if not path:
        return None
    try:
        parts = Path(path).parts
        idx = _find_base_index(parts)
        return str(Path(*parts[idx:]))
    except ValueError:
        return str(path)


def resolve_layer_and_domain(
    model, layer_order: list[str] | None = None, marts_layer: str = "marts"
) -> tuple[str | None, str | None]:
    if layer_order is None:
        layer_order = DEFAULT_LAYER_ORDER

    # 1. Try path first
    layer = None
    domain = None
    path = getattr(model, "path", getattr(model, "_path", None))
    if path:
        layer, domain = get_layer_and_domain(path, layer_order=layer_order)

    # Check if the resolved layer is actually a valid layer in layer_order
    if not layer or (layer_order and layer not in layer_order):
        layer = None
        domain = None

    # 2. Fall back to meta/tags for layer
    meta = getattr(model, "meta", {}) or {}
    tags = getattr(model, "tags", []) or []

    if not layer:
        if "layer" in meta:
            layer = str(meta["layer"])
        if not layer and tags:
            for tag in tags:
                if layer_order and tag in layer_order:
                    layer = tag
                    break

    # 3. Fall back to meta/tags for domain
    if not domain:
        if "domain" in meta:
            domain = str(meta["domain"])
        if not domain and tags:
            for tag in tags:
                if tag.startswith("domain:"):
                    domain = tag.split(":", 1)[1]
                    break

    return layer, domain
