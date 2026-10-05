from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch
import pytest

from conftest import _make_model
from tff.core.model import read_file_safe, read_model_sql


@pytest.mark.parametrize(
    "path_val",
    [None, "", "does_not_exist.sql", "\0invalid_path"],
)
def test_read_file_safe_invalid_or_missing(tmp_path: Path, path_val: str | None) -> None:
    if path_val == "does_not_exist.sql":
        target = tmp_path / path_val
        assert read_file_safe(str(target)) is None
        assert read_file_safe(target) is None
    else:
        assert read_file_safe(path_val) is None


def test_read_file_safe_directory(tmp_path: Path) -> None:
    assert read_file_safe(str(tmp_path)) is None
    assert read_file_safe(tmp_path) is None


def test_read_file_safe_valid_file(tmp_path: Path) -> None:
    f = tmp_path / "valid.sql"
    f.write_text("SELECT 1 AS col;", encoding="utf-8")
    assert read_file_safe(str(f)) == "SELECT 1 AS col;"
    assert read_file_safe(f) == "SELECT 1 AS col;"


def test_read_file_safe_exceptions(tmp_path: Path) -> None:
    f = tmp_path / "valid.sql"
    f.write_text("SELECT 1 AS col;", encoding="utf-8")

    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        assert read_file_safe(str(f)) is None

    with patch.object(Path, "is_file", return_value=False):
        assert read_file_safe(str(f)) is None

    with patch.object(Path, "is_file", side_effect=OSError("Permission denied")):
        assert read_file_safe(str(f)) is None


def test_read_file_safe_fifo(tmp_path: Path) -> None:
    if hasattr(os, "mkfifo"):
        fifo_path = tmp_path / "fifo_pipe"
        os.mkfifo(fifo_path)
        assert read_file_safe(fifo_path) is None
        assert read_file_safe(str(fifo_path)) is None


@pytest.mark.parametrize(
    ("prefer_file", "has_file", "query", "expected"),
    [
        (False, True, "SELECT 'from_query';", "SELECT 'from_query';"),
        (False, True, None, "SELECT 'from_file';"),
        (False, False, None, None),
        (True, True, "SELECT 'from_query';", "SELECT 'from_file';"),
        (True, False, "SELECT 'from_query';", "SELECT 'from_query';"),
        (True, False, None, None),
    ],
)
def test_read_model_sql_resolution(
    tmp_path: Path, prefer_file: bool, has_file: bool, query: str | None, expected: str | None
) -> None:
    file_path = ""
    if has_file:
        f = tmp_path / "model.sql"
        f.write_text("SELECT 'from_file';", encoding="utf-8")
        file_path = str(f)
    elif expected is not None or query is not None:
        file_path = str(tmp_path / "nonexistent.sql")

    model = _make_model(name="my_model", path=file_path, query=query)
    assert read_model_sql(model, prefer_file=prefer_file) == expected
    assert model.get_sql(prefer_file=prefer_file) == expected
    assert model.read_sql(prefer_file=prefer_file) == expected


def test_read_model_sql_prefer_file_directory_fallback(tmp_path: Path) -> None:
    model = _make_model(name="my_model", path=str(tmp_path), query="SELECT 'from_query';")
    assert model.get_sql(prefer_file=True) == "SELECT 'from_query';"


def test_read_model_sql_prefer_file_read_error_fallback(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT 'from_file';", encoding="utf-8")
    model = _make_model(name="my_model", path=str(f), query="SELECT 'from_query';")
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        assert model.get_sql(prefer_file=True) == "SELECT 'from_query';"


def test_model_representation_ast_from_file(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT id, name FROM users;", encoding="utf-8")
    model = _make_model(name="users_model", path=str(f), query=None)
    assert model.ast is not None


@pytest.mark.parametrize("prefer_file", [False, True])
def test_read_model_sql_with_project_root_relative(tmp_path: Path, prefer_file: bool) -> None:
    models_dir = tmp_path / "models" / "staging"
    models_dir.mkdir(parents=True, exist_ok=True)
    sql_file = models_dir / "stg_users.sql"
    sql_file.write_text("SELECT id FROM raw_users;", encoding="utf-8")

    model = _make_model(name="stg_users", path="models/staging/stg_users.sql", query=None)

    assert read_model_sql(model, prefer_file=prefer_file, project_root=tmp_path) == "SELECT id FROM raw_users;"
    assert model.get_sql(prefer_file=prefer_file, project_root=tmp_path) == "SELECT id FROM raw_users;"
    assert model.read_sql(prefer_file=prefer_file, project_root=tmp_path) == "SELECT id FROM raw_users;"
    assert read_model_sql(model, project_root=str(tmp_path)) == "SELECT id FROM raw_users;"


def test_read_model_sql_with_project_root_edge_cases(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT 'absolute';", encoding="utf-8")

    # Absolute path ignores project_root prepending
    model_abs = _make_model(name="my_model", path=str(f), query=None)
    dummy_root = tmp_path / "nonexistent_dir"
    assert read_model_sql(model_abs, project_root=dummy_root) == "SELECT 'absolute';"

    # Empty path returns None
    model_empty = _make_model(name="empty_path_model", path="", query=None)
    assert read_model_sql(model_empty, project_root=tmp_path) is None


def test_read_model_sql_raw_code_and_get_raw_sql() -> None:
    model_raw = _make_model(name="raw_model", path="models/raw.sql", raw_code="SELECT * FROM raw;")
    assert model_raw.get_sql(prefer_file=False) == "SELECT * FROM raw;"
    assert model_raw.get_raw_sql() == "SELECT * FROM raw;"

    model_both = _make_model(
        name="both_model",
        path="models/both.sql",
        query="SELECT * FROM compiled;",
        raw_code="SELECT * FROM raw;",
    )
    assert model_both.get_sql(prefer_file=False) == "SELECT * FROM compiled;"
    assert model_both.get_sql(prefer_file=True) == "SELECT * FROM raw;"
    assert model_both.get_raw_sql() == "SELECT * FROM raw;"
