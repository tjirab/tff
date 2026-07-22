"""Thread-local fitness function configuration for SQLMesh rule classes."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig

_config_local = threading.local()


def set_ff_config(config: FitnessFunctionsConfig) -> None:
    _config_local.config = config


def get_ff_config() -> FitnessFunctionsConfig:
    from tff.core.config import FitnessFunctionsConfig

    config = getattr(_config_local, "config", None)
    if config is None:
        config = FitnessFunctionsConfig()
        _config_local.config = config
    return config


def clear_ff_config() -> None:
    if hasattr(_config_local, "config"):
        del _config_local.config
