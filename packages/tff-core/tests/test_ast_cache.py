"""Unit tests for tff.core.ast_cache persistent disk-based caching."""

from pathlib import Path
from unittest.mock import patch
import pytest
import sqlglot.expressions as exp

from tff.core.ast_cache import (
    clear_ast_cache,
    compute_ast_cache_key,
    get_ast_cache_dir,
    get_cached_ast,
    is_cache_enabled,
    parse_sql_with_cache,
    set_cached_ast,
)
from tff.core.config import FitnessFunctionsConfig


def test_compute_ast_cache_key():
    sql1 = "SELECT a, b FROM tbl"
    sql2 = "  SELECT a, b FROM tbl  \n"
    sql3 = "SELECT x FROM tbl"

    # Whitespace normalization
    assert compute_ast_cache_key(sql1, "duckdb") == compute_ast_cache_key(sql2, "duckdb")
    # Different dialects produce different keys
    assert compute_ast_cache_key(sql1, "duckdb") != compute_ast_cache_key(sql1, "postgres")
    # Different SQL produces different keys
    assert compute_ast_cache_key(sql1, "duckdb") != compute_ast_cache_key(sql3, "duckdb")


def test_get_ast_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Default path
    default_dir = get_ast_cache_dir(tmp_path)
    assert default_dir == tmp_path / ".tff_cache" / "ast"

    # Custom dir parameter
    custom = tmp_path / "custom_cache"
    assert get_ast_cache_dir(tmp_path, custom_dir=custom) == custom / "ast"

    # Custom relative dir
    assert get_ast_cache_dir(tmp_path, custom_dir=".custom_cache") == tmp_path / ".custom_cache" / "ast"

    # Custom dir already ending in 'ast'
    already_ast = tmp_path / "custom" / "ast"
    assert get_ast_cache_dir(tmp_path, custom_dir=already_ast) == already_ast

    # Environment variable override
    env_dir = tmp_path / "env_cache"
    monkeypatch.setenv("TFF_CACHE_DIR", str(env_dir))
    assert get_ast_cache_dir(tmp_path) == env_dir / "ast"


def test_is_cache_enabled(monkeypatch: pytest.MonkeyPatch):
    config = FitnessFunctionsConfig()
    assert is_cache_enabled(config) is True
    assert is_cache_enabled(None) is True

    # Config disable
    config.cache_ast = False
    assert is_cache_enabled(config) is False

    # Env var TFF_NO_CACHE
    config.cache_ast = True
    monkeypatch.setenv("TFF_NO_CACHE", "1")
    assert is_cache_enabled(config) is False

    # Env var TFF_DISABLE_CACHE
    monkeypatch.delenv("TFF_NO_CACHE")
    monkeypatch.setenv("TFF_DISABLE_CACHE", "true")
    assert is_cache_enabled(config) is False


def test_set_and_get_cached_ast(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sql = "SELECT 1 AS num"
    dialect = "duckdb"
    key = compute_ast_cache_key(sql, dialect)

    # Initial state: cache miss
    assert get_cached_ast(key, cache_dir=cache_dir) is None

    # Parse and set
    parsed = parse_sql_with_cache(sql, dialect=dialect, cache_dir=cache_dir)
    assert isinstance(parsed, exp.Expression)

    # Cache hit
    loaded = get_cached_ast(key, cache_dir=cache_dir)
    assert loaded is not None
    assert isinstance(loaded, exp.Expression)
    assert loaded.sql(dialect=dialect) == "SELECT 1 AS num"


def test_get_cached_ast_corrupted_file(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    key = "ab1234567890abcdef"
    subdir = cache_dir / key[:2]
    subdir.mkdir(parents=True, exist_ok=True)
    corrupted_file = subdir / f"{key[2:]}.ast"
    corrupted_file.write_bytes(b"corrupted pickle data")

    # Should safely return None and remove the corrupted file
    assert get_cached_ast(key, cache_dir=cache_dir) is None
    assert not corrupted_file.exists()


def test_set_cached_ast_error_handling(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sql = "SELECT 1"
    key = compute_ast_cache_key(sql, "duckdb")

    with patch("tempfile.NamedTemporaryFile", side_effect=OSError("Disk full")):
        # Should not raise exception
        set_cached_ast(key, exp.Literal.number(1), cache_dir=cache_dir)

    # Test failure during replace cleans up the temporary file
    with patch("pathlib.Path.replace", side_effect=OSError("Permission denied")):
        set_cached_ast(key, exp.Literal.number(1), cache_dir=cache_dir)
        # Verify no orphaned .tmp files remain
        assert list(cache_dir.glob("**/*.tmp")) == []


def test_parse_sql_with_cache_empty_and_disabled(tmp_path: Path):
    cache_dir = tmp_path / "cache"

    # Empty SQL
    assert parse_sql_with_cache("", "duckdb", cache_dir=cache_dir) is None
    assert parse_sql_with_cache("   \n", "duckdb", cache_dir=cache_dir) is None

    # Disabled cache
    sql = "SELECT 42"
    parsed_disabled = parse_sql_with_cache(
        sql, "duckdb", cache_dir=cache_dir, enabled=False
    )
    assert parsed_disabled is not None
    # Verify no file written when disabled
    assert not cache_dir.exists()

    # Invalid SQL with disabled cache
    assert parse_sql_with_cache("SELECT FROM WHERE", "duckdb", enabled=False) is None

    # Invalid SQL with enabled cache
    assert parse_sql_with_cache("SELECT FROM WHERE", "duckdb", cache_dir=cache_dir) is None


def test_parse_sql_with_cache_respects_no_cache_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache_dir = tmp_path / "cache"
    sql = "SELECT 42"

    # Test TFF_NO_CACHE=1
    monkeypatch.setenv("TFF_NO_CACHE", "1")
    parsed = parse_sql_with_cache(sql, "duckdb", cache_dir=cache_dir)
    assert parsed is not None
    assert not cache_dir.exists()

    # Invalid SQL when TFF_NO_CACHE=1
    assert parse_sql_with_cache("SELECT FROM WHERE", "duckdb", cache_dir=cache_dir) is None

    # Test TFF_DISABLE_CACHE=1
    monkeypatch.delenv("TFF_NO_CACHE")
    monkeypatch.setenv("TFF_DISABLE_CACHE", "1")
    parsed2 = parse_sql_with_cache(sql, "duckdb", cache_dir=cache_dir)
    assert parsed2 is not None
    assert not cache_dir.exists()


def test_model_representation_ast_respects_no_cache_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tff.core.model import ModelRepresentation

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("TFF_NO_CACHE", "1")
    m = ModelRepresentation(name="test", path="test.sql", dialect="duckdb", query="SELECT 42")
    ast = m.ast
    assert ast is not None
    assert not (tmp_path / ".tff_cache").exists()


def test_parse_sql_with_cache_hit_and_miss(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    sql = "SELECT id, name FROM users WHERE active = true"
    dialect = "postgres"

    # 1. First call: miss + parse + write
    parsed1 = parse_sql_with_cache(sql, dialect, cache_dir=cache_dir)
    assert parsed1 is not None

    # 2. Second call: hit from cache
    with patch("sqlglot.parse_one") as mock_parse:
        parsed2 = parse_sql_with_cache(sql, dialect, cache_dir=cache_dir)
        mock_parse.assert_not_called()
        assert parsed2 is not None
        assert parsed2.sql(dialect=dialect) == parsed1.sql(dialect=dialect)


def test_clear_ast_cache(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Empty cache returns 0
    assert clear_ast_cache(custom_dir=cache_dir) == 0

    # Nonexistent cache returns 0
    nonexistent = tmp_path / "nonexistent"
    assert clear_ast_cache(custom_dir=nonexistent) == 0

    # Populate cache files
    sql1 = "SELECT 1"
    sql2 = "SELECT 2"
    parse_sql_with_cache(sql1, "duckdb", cache_dir=cache_dir)
    parse_sql_with_cache(sql2, "duckdb", cache_dir=cache_dir)

    # Subdirectory that cannot be deleted because it contains a non-ast file
    non_empty = cache_dir / "keep_dir"
    non_empty.mkdir()
    (non_empty / "other.txt").touch()

    # Add orphaned temp file to ensure it gets cleared
    (cache_dir / "orphaned.tmp").touch()

    cleared = clear_ast_cache(custom_dir=cache_dir)
    assert cleared == 3
    assert list(cache_dir.glob("**/*.ast")) == []
    assert list(cache_dir.glob("**/*.tmp")) == []
    assert non_empty.exists()
