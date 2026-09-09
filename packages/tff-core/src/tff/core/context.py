"""Thread-local fitness function configuration for SQLMesh rule classes (deprecated)."""

from __future__ import annotations

import threading
import warnings
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig

_config_local = threading.local()


def set_ff_config(config: FitnessFunctionsConfig) -> None:
    _config_local.config = config


def get_ff_config() -> FitnessFunctionsConfig:
    warnings.warn(
        "tff.core.context.get_ff_config() is deprecated and will be removed in a future release. "
        "Pass FitnessFunctionsConfig explicitly instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    from tff.core.config import FitnessFunctionsConfig

    config = getattr(_config_local, "config", None)
    if config is None:
        config = FitnessFunctionsConfig()
        _config_local.config = config
    return config


def clear_ff_config() -> None:
    if hasattr(_config_local, "config"):
        del _config_local.config
