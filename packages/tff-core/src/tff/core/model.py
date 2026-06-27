from __future__ import annotations

from dataclasses import dataclass, field


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

