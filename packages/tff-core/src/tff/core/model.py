from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import sqlglot.expressions


def read_file_safe(
    file_path: str | Path | None,
    *,
    raise_on_error: bool = False,
    model_name: str | None = None,
    expected_type: str = "file",
) -> str | None:
    """Safely read a text file as UTF-8, handling non-existent paths, directories, and I/O errors.

    Args:
        file_path: Path to the file (str, Path, or None).
        raise_on_error: If True, raises normalized TffError instead of returning None on failure.
        model_name: Optional model name for error attribution.
        expected_type: Expected file type description (e.g. 'file', 'SQL file').

    Returns:
        File contents as string, or None if the path is invalid/unreadable and raise_on_error is False.

    Raises:
        TffFileError | TffModelError: If raise_on_error is True and the file cannot be read or is invalid.
    """
    if not file_path:
        if raise_on_error:
            from tff.core.exceptions import TffFileError

            raise TffFileError("No file path was provided.", operation="read")
        return None

    try:
        path = Path(file_path)
        if path.is_dir():
            if raise_on_error:
                import errno
                from tff.core.exceptions import normalize_os_error

                raise normalize_os_error(
                    IsADirectoryError(errno.EISDIR, "Is a directory", str(path)),
                    path=path,
                    operation="read",
                    model_name=model_name,
                    expected_type=expected_type,
                )
            return None

        if not path.is_file():
            if raise_on_error:
                import errno
                from tff.core.exceptions import normalize_os_error

                raise normalize_os_error(
                    FileNotFoundError(errno.ENOENT, "No such file", str(path)),
                    path=path,
                    operation="read",
                    model_name=model_name,
                    expected_type=expected_type,
                )
            return None

        return path.read_text(encoding="utf-8")
    except Exception as e:
        if raise_on_error:
            from tff.core.exceptions import TffError, normalize_os_error

            if isinstance(e, TffError):
                raise e
            raise normalize_os_error(
                e,
                path=file_path,
                operation="read",
                model_name=model_name,
                expected_type=expected_type,
            ) from e
        return None


def read_model_sql(
    model: ModelRepresentation,
    *,
    prefer_file: bool = False,
    project_root: str | Path | None = None,
    raise_on_error: bool = False,
) -> str | None:
    """Read SQL content for a model from disk or query attribute safely.

    Args:
        model: The model representation.
        prefer_file: If True, attempts to read from disk (model.path) first,
            falling back to model.query if reading fails or file does not exist.
            If False (default), returns model.query if present, falling back to disk.
        project_root: Optional project root directory. If provided and model.path is relative,
            resolves model.path against this root path.
        raise_on_error: If True and SQL content cannot be obtained from file or query,
            raises a TffModelError.

    Returns:
        The SQL content as a string, or None if unavailable or unreadable.

    Raises:
        TffModelError: If raise_on_error is True and SQL content is unavailable or unreadable.
    """
    target_path: Path | str | None = model.path
    if target_path and project_root is not None:
        p = Path(target_path)
        if not p.is_absolute():
            target_path = Path(project_root) / p

    if prefer_file:
        disk_sql = read_file_safe(
            target_path,
            raise_on_error=False,
            model_name=model.name,
            expected_type="SQL file",
        )
        if disk_sql is not None:
            return disk_sql
        if model.query is not None:
            return model.query
        if raise_on_error:
            return read_file_safe(
                target_path,
                raise_on_error=True,
                model_name=model.name,
                expected_type="SQL file",
            )
        return None

    if model.query is not None:
        return model.query
    return read_file_safe(
        target_path,
        raise_on_error=raise_on_error,
        model_name=model.name,
        expected_type="SQL file",
    )


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

    def get_sql(
        self,
        *,
        prefer_file: bool = False,
        project_root: str | Path | None = None,
        raise_on_error: bool = False,
    ) -> str | None:
        """Return SQL content for this model safely, either from disk or from the query attribute."""
        return read_model_sql(
            self,
            prefer_file=prefer_file,
            project_root=project_root,
            raise_on_error=raise_on_error,
        )

    def read_sql(
        self,
        *,
        prefer_file: bool = False,
        project_root: str | Path | None = None,
        raise_on_error: bool = False,
    ) -> str | None:
        """Alias for get_sql."""
        return self.get_sql(
            prefer_file=prefer_file,
            project_root=project_root,
            raise_on_error=raise_on_error,
        )

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



