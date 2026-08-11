"""Path helpers for layer and domain resolution."""

from __future__ import annotations

from pathlib import Path


def get_layer_from_path(path: str, layer_order: list[str] | None = None) -> str | None:
    parts = Path(path).parts
    try:
        models_index = parts.index("models")
        if layer_order is None:
            from tff.core.context import get_ff_config
            layer_order = get_ff_config().layers.order

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
        models_index = parts.index("models")
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


def get_layer_and_domain(path: str) -> tuple[str | None, str | None]:
    parts = Path(path).parts
    try:
        models_index = parts.index("models")
        from tff.core.context import get_ff_config
        layer_order = get_ff_config().layers.order

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

        if domain and domain.endswith(".sql"):
            domain = domain[:-4]

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
