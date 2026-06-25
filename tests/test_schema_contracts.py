"""Tests for schema contract path resolution."""

from pathlib import Path

import pytest

from sqlmesh_ff.checks.schema_contracts import _resolve_path


def test_resolve_path_valid_relative(tmp_path: Path) -> None:
    models_dir = tmp_path / "models" / "core"
    models_dir.mkdir(parents=True)
    model_file = models_dir / "dim_customer.sql"
    model_file.write_text("SELECT 1", encoding="utf-8")

    resolved = _resolve_path(tmp_path, "models/core", "dim_customer.sql")

    assert resolved == model_file.resolve()


def test_resolve_path_rejects_parent_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="resolves outside project root"):
        _resolve_path(tmp_path, "models", "../../outside.sql")


def test_resolve_path_rejects_absolute_outside_root(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="resolves outside project root"):
        _resolve_path(tmp_path, "/etc", "passwd")
