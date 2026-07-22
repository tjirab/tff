"""Path helpers for layer and domain resolution."""

from __future__ import annotations

from pathlib import Path


def get_layer_from_path(path: str, layer_order: list[str] | None = None) -> str | None:
    parts = Path(path).parts
    try:
        models_index = parts.index("models")
        layer = parts[models_index + 1]
        if layer_order and layer not in layer_order:
            return layer
        return layer
    except (ValueError, IndexError):
        return None


def get_marts_domain_from_path(path: str, layer_name: str = "marts") -> str | None:
    parts = Path(path).parts
    try:
        models_index = parts.index("models")
        layer = parts[models_index + 1]
        if layer != layer_name:
            return None
        return parts[models_index + 2]
    except (ValueError, IndexError):
        return None


def get_layer_and_domain(path: str) -> tuple[str | None, str | None]:
    parts = Path(path).parts
    try:
        models_index = parts.index("models")
        layer = parts[models_index + 1]
        if len(parts) > models_index + 2:
            domain = parts[models_index + 2]
            if domain.endswith(".sql"):
                domain = domain[:-4]
        else:
            domain = None
        return layer, domain
    except (ValueError, IndexError):
        return None, None


def model_path_relative(model) -> str | None:
    path = getattr(model, "path", getattr(model, "_path", None))
    if not path:
        return None
    try:
        parts = Path(path).parts
        idx = parts.index("models")
        return str(Path(*parts[idx:]))
    except ValueError:
        return str(path)
