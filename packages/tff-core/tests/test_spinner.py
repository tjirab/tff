"""Tests for tff terminal spinner symbols (■ ▲ ●) and registration."""

from __future__ import annotations

from rich._spinners import SPINNERS
from rich.console import Console
from rich.progress import Progress, SpinnerColumn
from rich.status import Status

from tff.core.spinner import (
    TFF_SPINNER_FRAMES,
    TFF_SPINNER_INTERVAL,
    TFF_SPINNER_NAME,
    get_progress,
    get_status,
    register_tff_spinner,
)


def test_tff_spinner_registration() -> None:
    """Verify that tff spinner is registered in Rich's SPINNERS table with correct frames."""
    register_tff_spinner()

    assert TFF_SPINNER_NAME in SPINNERS
    assert SPINNERS[TFF_SPINNER_NAME]["frames"] == ["■", "▲", "●"]
    assert SPINNERS[TFF_SPINNER_NAME]["interval"] == TFF_SPINNER_INTERVAL
    assert TFF_SPINNER_INTERVAL == 250
    assert TFF_SPINNER_FRAMES == ["■", "▲", "●"]


def test_get_status_creates_tff_spinner() -> None:
    """Verify that get_status instantiates a Status with the tff spinner."""
    console = Console(record=True, stderr=True)
    status = get_status("Evaluating fitness functions...", console=console)

    assert isinstance(status, Status)
    assert status._spinner.name == "tff"
    assert status._spinner.frames == ["■", "▲", "●"]


def test_tff_spinner_animation_renders_symbols() -> None:
    """Verify that the spinner animation renders each symbol in sequence."""
    console = Console(record=True)
    status = get_status("Checking...", console=console)

    # Render at t=0.0s (first frame: ■)
    renderable_0 = status._spinner.render(0.0)
    # Render at t=0.26s (second frame: ▲)
    renderable_1 = status._spinner.render(0.26)
    # Render at t=0.51s (third frame: ●)
    renderable_2 = status._spinner.render(0.51)

    c0 = Console(record=True)
    c0.print(renderable_0)
    out0 = c0.export_text()
    assert "■" in out0

    c1 = Console(record=True)
    c1.print(renderable_1)
    out1 = c1.export_text()
    assert "▲" in out1

    c2 = Console(record=True)
    c2.print(renderable_2)
    out2 = c2.export_text()
    assert "●" in out2


def test_get_progress_creates_tff_progress() -> None:
    """Verify that get_progress configures a Progress bar using the tff spinner."""
    console = Console(record=True, stderr=True)
    progress = get_progress(console=console)

    assert isinstance(progress, Progress)
    spinner_cols = [c for c in progress.columns if isinstance(c, SpinnerColumn)]
    assert len(spinner_cols) == 1
    assert spinner_cols[0].spinner.name == "tff"

    with progress:
        task_id = progress.add_task("Fixing...", total=10)
        progress.update(task_id, advance=5, description="Halfway...")
        task = progress.tasks[0]
        assert task.completed == 5
        assert task.description == "Halfway..."
