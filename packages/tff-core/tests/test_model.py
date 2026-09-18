from pathlib import Path
from unittest.mock import patch

from tff.core.model import ModelRepresentation, read_file_safe, read_model_sql


def test_read_file_safe_none_or_empty() -> None:
    assert read_file_safe(None) is None
    assert read_file_safe("") is None


def test_read_file_safe_nonexistent(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.sql"
    assert read_file_safe(str(non_existent)) is None
    assert read_file_safe(non_existent) is None


def test_read_file_safe_directory(tmp_path: Path) -> None:
    assert read_file_safe(str(tmp_path)) is None
    assert read_file_safe(tmp_path) is None


def test_read_file_safe_valid_file(tmp_path: Path) -> None:
    f = tmp_path / "valid.sql"
    f.write_text("SELECT 1 AS col;", encoding="utf-8")
    assert read_file_safe(str(f)) == "SELECT 1 AS col;"
    assert read_file_safe(f) == "SELECT 1 AS col;"


def test_read_file_safe_read_exception(tmp_path: Path) -> None:
    f = tmp_path / "valid.sql"
    f.write_text("SELECT 1 AS col;", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        assert read_file_safe(str(f)) is None


def test_read_file_safe_path_instantiation_exception() -> None:
    assert read_file_safe("\0invalid_path") is None


def test_read_model_sql_prefer_file_false_with_query(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT 'from_file';", encoding="utf-8")

    model = ModelRepresentation(
        name="my_model",
        path=str(f),
        dialect="duckdb",
        query="SELECT 'from_query';",
    )
    # Default prefer_file=False returns query without checking disk
    assert read_model_sql(model) == "SELECT 'from_query';"
    assert model.get_sql() == "SELECT 'from_query';"
    assert model.read_sql() == "SELECT 'from_query';"


def test_read_model_sql_prefer_file_false_without_query(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT 'from_file';", encoding="utf-8")

    model = ModelRepresentation(
        name="my_model",
        path=str(f),
        dialect="duckdb",
        query=None,
    )
    assert read_model_sql(model) == "SELECT 'from_file';"
    assert model.get_sql() == "SELECT 'from_file';"
    assert model.read_sql() == "SELECT 'from_file';"


def test_read_model_sql_prefer_file_false_nonexistent() -> None:
    model = ModelRepresentation(
        name="my_model",
        path="nonexistent_file.sql",
        dialect="duckdb",
        query=None,
    )
    assert model.get_sql() is None


def test_read_model_sql_prefer_file_false_empty_path() -> None:
    model = ModelRepresentation(
        name="my_model",
        path="",
        dialect="duckdb",
        query=None,
    )
    assert model.get_sql() is None


def test_read_model_sql_prefer_file_true_prefers_file(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT 'from_file';", encoding="utf-8")

    model = ModelRepresentation(
        name="my_model",
        path=str(f),
        dialect="duckdb",
        query="SELECT 'from_query';",
    )
    assert read_model_sql(model, prefer_file=True) == "SELECT 'from_file';"
    assert model.get_sql(prefer_file=True) == "SELECT 'from_file';"
    assert model.read_sql(prefer_file=True) == "SELECT 'from_file';"


def test_read_model_sql_prefer_file_true_fallback_on_missing(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.sql"
    model = ModelRepresentation(
        name="my_model",
        path=str(non_existent),
        dialect="duckdb",
        query="SELECT 'from_query';",
    )
    assert model.get_sql(prefer_file=True) == "SELECT 'from_query';"


def test_read_model_sql_prefer_file_true_fallback_on_directory(tmp_path: Path) -> None:
    model = ModelRepresentation(
        name="my_model",
        path=str(tmp_path),
        dialect="duckdb",
        query="SELECT 'from_query';",
    )
    assert model.get_sql(prefer_file=True) == "SELECT 'from_query';"


def test_read_model_sql_prefer_file_true_fallback_on_read_error(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT 'from_file';", encoding="utf-8")

    model = ModelRepresentation(
        name="my_model",
        path=str(f),
        dialect="duckdb",
        query="SELECT 'from_query';",
    )
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        assert model.get_sql(prefer_file=True) == "SELECT 'from_query';"


def test_read_model_sql_prefer_file_true_none_when_both_unavailable(tmp_path: Path) -> None:
    non_existent = tmp_path / "does_not_exist.sql"
    model = ModelRepresentation(
        name="my_model",
        path=str(non_existent),
        dialect="duckdb",
        query=None,
    )
    assert model.get_sql(prefer_file=True) is None


def test_model_representation_ast_from_file(tmp_path: Path) -> None:
    f = tmp_path / "model.sql"
    f.write_text("SELECT id, name FROM users;", encoding="utf-8")

    model = ModelRepresentation(
        name="users_model",
        path=str(f),
        dialect="duckdb",
        query=None,
    )
    assert model.ast is not None
