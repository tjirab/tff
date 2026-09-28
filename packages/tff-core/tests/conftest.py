"""Shared test fixtures and lightweight object factories."""

from __future__ import annotations

from typing import Any
import pytest

from tff.core.model import ModelRepresentation
from tff.core.report import LintFinding, Severity


def _make_finding(
    check: str = "banselectstar",
    severity: Severity = "error",
    message: str = "Rule violation",
    model: str | None = None,
    path: str | None = None,
    line: int | None = None,
    col: int | None = None,
    end_line: int | None = None,
    end_col: int | None = None,
    msg: str | None = None,
    **kwargs: Any,
) -> LintFinding:
    """Lightweight factory for LintFinding with sensible defaults."""
    if msg is not None:
        message = msg
    return LintFinding(
        check=check,
        severity=severity,
        message=message,
        model=model,
        path=path,
        line=line,
        col=col,
        end_line=end_line,
        end_col=end_col,
        **kwargs,
    )


def _make_model(
    name: str = "test_model",
    path: str = "models/test_model.sql",
    dialect: str = "duckdb",
    is_symbolic: bool = False,
    is_external: bool = False,
    **kwargs: Any,
) -> ModelRepresentation:
    """Lightweight factory for ModelRepresentation with sensible defaults."""
    return ModelRepresentation(
        name=name,
        path=path,
        dialect=dialect,
        is_symbolic=is_symbolic,
        is_external=is_external,
        **kwargs,
    )


@pytest.fixture
def make_finding():
    """Pytest fixture providing the _make_finding factory function."""
    return _make_finding


@pytest.fixture
def make_model():
    """Pytest fixture providing the _make_model factory function."""
    return _make_model
