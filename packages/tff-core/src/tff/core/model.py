from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import sqlglot.expressions


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

    @property
    def ast(self) -> sqlglot.expressions.Expression | None:
        """Get the cached AST (expression) or parse the query/file if not already cached."""
        if self.expression is not None:
            return self.expression

        sql = self.query
        if sql is None:
            from pathlib import Path
            path = Path(self.path)
            if not path.exists():
                return None
            try:
                sql = path.read_text(encoding="utf-8")
            except Exception:
                return None

        # Clean/strip SQLMesh MODEL block if present
        import re
        import sqlglot
        cleaned_sql = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
        try:
            self.expression = sqlglot.parse_one(cleaned_sql, read=self.dialect)
        except Exception:
            return None
        return self.expression



