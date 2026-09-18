from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlglot.expressions


def read_file_safe(file_path: str | Path | None) -> str | None:
    """Safely read a text file as UTF-8, handling non-existent paths, directories, and I/O errors.

    Args:
        file_path: Path to the file (str, Path, or None).

    Returns:
        File contents as string, or None if the path is invalid, not a regular file, or unreadable.
    """
    if not file_path:
        return None
    try:
        path = Path(file_path)
        if not path.exists() or path.is_dir():
            return None
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def read_model_sql(model: ModelRepresentation, *, prefer_file: bool = False) -> str | None:
    """Read SQL content for a model from disk or query attribute safely.

    Args:
        model: The model representation.
        prefer_file: If True, attempts to read from disk (model.path) first,
            falling back to model.query if reading fails or file does not exist.
            If False (default), returns model.query if present, falling back to disk.

    Returns:
        The SQL content as a string, or None if unavailable or unreadable.
    """
    if prefer_file:
        disk_sql = read_file_safe(model.path)
        if disk_sql is not None:
            return disk_sql
        return model.query

    if model.query is not None:
        return model.query
    return read_file_safe(model.path)


@dataclass
class ModelRepresentation:
    name: str
    path: str
    dialect: str
    is_symbolic: bool = False
    is_external: bool = False
    columns_to_types: dict[str, str] = field(default_factory=dict)
    depends_on: set[str] = field(default_factory=set)
    description: str | None = None
    owner: str | None = None
    grains: list[str] = field(default_factory=list)
    # Audits represent assertions/tests, e.g. [("not_null", {"columns": ["id"]})]
    audits: list[tuple[str, dict]] = field(default_factory=list)
    query: str | None = None
    materialized: str | None = None
    expression: sqlglot.expressions.Expression | None = field(default=None, repr=False, compare=False)
    tags: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    provider: str | None = None

    def get_sql(self, *, prefer_file: bool = False) -> str | None:
        """Return SQL content for this model safely, either from disk or from the query attribute."""
        return read_model_sql(self, prefer_file=prefer_file)

    def read_sql(self, *, prefer_file: bool = False) -> str | None:
        """Alias for get_sql."""
        return self.get_sql(prefer_file=prefer_file)

    @property
    def ast(self) -> sqlglot.expressions.Expression | None:
        """Get the cached AST (expression) or parse the query/file if not already cached."""
        if self.expression is not None:
            return self.expression

        sql = self.get_sql()
        if sql is None:
            return None

        # Clean/strip SQLMesh MODEL block and Dataform/Jinja blocks if present
        import re
        from tff.core.utils.jinja import clean_dataform_for_parsing, clean_jinja_for_parsing

        cleaned_sql = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
        cleaned_sql = clean_dataform_for_parsing(cleaned_sql)
        cleaned_sql = clean_jinja_for_parsing(cleaned_sql, provider=self.provider)
        try:
            from tff.core.ast_cache import parse_sql_with_cache

            self.expression = parse_sql_with_cache(cleaned_sql, dialect=self.dialect)
        except Exception:
            return None
        return self.expression



