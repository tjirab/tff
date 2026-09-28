"""tff terminal spinner registration and helpers."""

from __future__ import annotations

from rich._spinners import SPINNERS
from rich.console import Console
from rich.status import Status

TFF_SPINNER_NAME = "tff"
TFF_SPINNER_FRAMES = ["■", "▲", "●"]
TFF_SPINNER_INTERVAL = 250  # milliseconds


def register_tff_spinner() -> None:
    """Register the signature tff spinner (■ ▲ ●) in Rich's spinner catalog."""
    SPINNERS[TFF_SPINNER_NAME] = {
        "interval": TFF_SPINNER_INTERVAL,
        "frames": TFF_SPINNER_FRAMES,
    }


# Automatically register on import
register_tff_spinner()


def get_status(
    status: str,
    *,
    console: Console | None = None,
    speed: float = 1.0,
    refresh_per_second: float = 12.5,
) -> Status:
    """Create a Rich Status spinner using tff's signature symbols (■ ▲ ●)."""
    register_tff_spinner()
    return Status(
        status,
        console=console or Console(stderr=True),
        spinner=TFF_SPINNER_NAME,
        speed=speed,
        refresh_per_second=refresh_per_second,
    )
