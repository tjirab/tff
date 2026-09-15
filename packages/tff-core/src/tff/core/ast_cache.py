"""Persistent disk-based AST caching for SQLGlot expressions."""

from __future__ import annotations

import hashlib
import logging
import os
import pickle
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlglot.expressions as exp
    from tff.core.config import FitnessFunctionsConfig

logger = logging.getLogger(__name__)

DEFAULT_CACHE_DIR_NAME = ".tff_cache"
AST_CACHE_SUBDIR = "ast"


def get_ast_cache_dir(
    project_root: Path | None = None,
    custom_dir: Path | str | None = None,
) -> Path:
    """Resolve the directory for storing AST cache files."""
    if custom_dir:
        p = Path(custom_dir)
        if not p.is_absolute() and project_root:
            p = project_root / p
        if p.name == AST_CACHE_SUBDIR:
            return p
        return p / AST_CACHE_SUBDIR
    env_dir = os.environ.get("TFF_CACHE_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.name == AST_CACHE_SUBDIR:
            return p
        return p / AST_CACHE_SUBDIR
    root = project_root or Path.cwd()
    return root / DEFAULT_CACHE_DIR_NAME / AST_CACHE_SUBDIR


def is_cache_enabled(config: FitnessFunctionsConfig | None = None) -> bool:
    """Check if AST caching is enabled via environment variables or configuration."""
    if os.environ.get("TFF_NO_CACHE", "").strip().lower() in ("1", "true", "yes"):
        return False
    if os.environ.get("TFF_DISABLE_CACHE", "").strip().lower() in ("1", "true", "yes"):
        return False
    if config is not None and not getattr(config, "cache_ast", True):
        return False
    return True


def compute_ast_cache_key(sql: str, dialect: str) -> str:
    """Compute a SHA-256 cache key based on SQLGlot version, dialect, and SQL content."""
    import sqlglot

    normalized = sql.strip()
    key_payload = f"{sqlglot.__version__}:{dialect}:{normalized}".encode("utf-8")
    return hashlib.sha256(key_payload).hexdigest()


def get_cached_ast(
    cache_key: str,
    cache_dir: Path | None = None,
    project_root: Path | None = None,
) -> exp.Expression | None:
    """Retrieve a cached AST expression from disk by cache key if available."""
    target_dir = cache_dir or get_ast_cache_dir(project_root)
    cache_file = target_dir / cache_key[:2] / f"{cache_key[2:]}.ast"
    if not cache_file.exists():
        logger.debug("AST cache miss for key %s", cache_key[:12])
        return None

    try:
        data = cache_file.read_bytes()
        expr = pickle.loads(data)
        logger.debug("AST cache hit for key %s (%s)", cache_key[:12], cache_file.name)
        return expr
    except Exception as exc:
        logger.debug("Failed to load cached AST from %s: %s", cache_file, exc)
        cache_file.unlink(missing_ok=True)
        return None


def set_cached_ast(
    cache_key: str,
    expression: exp.Expression,
    cache_dir: Path | None = None,
    project_root: Path | None = None,
) -> None:
    """Atomically store an AST expression into the disk cache."""
    target_dir = cache_dir or get_ast_cache_dir(project_root)
    subdir = target_dir / cache_key[:2]
    temp_path: Path | None = None
    try:
        subdir.mkdir(parents=True, exist_ok=True)
        data = pickle.dumps(expression, protocol=pickle.HIGHEST_PROTOCOL)

        # Atomic file write using a temporary file in the same directory
        with tempfile.NamedTemporaryFile(dir=subdir, delete=False, suffix=".tmp") as tf:
            tf.write(data)
            temp_path = Path(tf.name)

        target_file = subdir / f"{cache_key[2:]}.ast"
        temp_path.replace(target_file)
        logger.debug("Cached AST stored for key %s (%s)", cache_key[:12], target_file.name)
    except Exception as exc:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        logger.debug("Failed to write cached AST to %s: %s", target_dir, exc)


def parse_sql_with_cache(
    sql: str,
    dialect: str,
    cache_dir: Path | None = None,
    project_root: Path | None = None,
    enabled: bool = True,
) -> exp.Expression | None:
    """Parse SQL using SQLGlot, using disk cache if enabled and allowed by environment."""
    import sqlglot

    if not sql or not sql.strip():
        return None

    if not enabled or not is_cache_enabled():
        try:
            return sqlglot.parse_one(sql, read=dialect)
        except Exception:
            return None

    cache_key = compute_ast_cache_key(sql, dialect)
    cached = get_cached_ast(cache_key, cache_dir=cache_dir, project_root=project_root)
    if cached is not None:
        return cached

    try:
        expression = sqlglot.parse_one(sql, read=dialect)
    except Exception:
        return None

    if expression is not None:
        set_cached_ast(cache_key, expression, cache_dir=cache_dir, project_root=project_root)

    return expression


def clear_ast_cache(
    project_root: Path | None = None,
    custom_dir: Path | str | None = None,
) -> int:
    """Remove all cached AST files and return the number of deleted files."""
    target_dir = get_ast_cache_dir(project_root, custom_dir=custom_dir)
    if not target_dir.exists():
        return 0

    count = 0
    for pattern in ("**/*.ast", "**/*.tmp"):
        for cached_file in target_dir.glob(pattern):
            cached_file.unlink(missing_ok=True)
            count += 1

    # Clean up empty subdirectories
    for sub in list(target_dir.iterdir()):
        if sub.is_dir():
            try:
                sub.rmdir()
            except OSError:
                pass

    return count
