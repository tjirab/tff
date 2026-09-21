"""Check to validate type parity for joined columns (Connascence of Type - CoT)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope

from tff.core.report import LintFinding
from tff.core.utils.paths import get_layer_from_path, model_path_relative

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation


DEFAULT_EQUIVALENT_TYPES: dict[str, set[str]] = {
    "text": {"text", "varchar", "string", "char", "nvarchar", "bpchar", "nchar"},
    "integer": {
        "int",
        "integer",
        "bigint",
        "smallint",
        "tinyint",
        "int2",
        "int4",
        "int8",
        "int16",
        "int32",
        "int64",
        "uint",
        "ubigint",
        "usmallint",
        "utinyint",
    },
    "numeric": {"decimal", "numeric", "number", "fixed", "bignumeric", "bigdecimal"},
    "float": {
        "float",
        "double",
        "real",
        "float4",
        "float8",
        "double precision",
        "float64",
        "float32",
    },
    "timestamp": {
        "timestamp",
        "timestamptz",
        "timestamp_ntz",
        "timestamp_ltz",
        "timestamp_tz",
        "datetime",
        "date",
    },
    "boolean": {"boolean", "bool"},
}


def normalize_type_string(raw_type: str | exp.DataType | None) -> str:
    """Normalize raw SQL data type string (e.g. VARCHAR(255) -> varchar)."""
    if raw_type is None:
        return ""
    if isinstance(raw_type, exp.DataType):
        raw_type = raw_type.sql()
    s = str(raw_type).strip().lower()
    s = re.sub(r"\(.*?\)", "", s).strip()
    s = re.sub(r"\[\]", "", s).strip()
    return s


def are_types_equivalent(
    type_a: str,
    type_b: str,
    equivalent_types: dict[str, set[str]],
) -> bool:
    """Return True if two normalized SQL types are identical or belong to the same equivalent group."""
    norm_a = normalize_type_string(type_a)
    norm_b = normalize_type_string(type_b)

    if not norm_a or not norm_b:
        return True
    if norm_a in ("unknown", "null") or norm_b in ("unknown", "null"):
        return True
    if norm_a == norm_b:
        return True

    # Check sqlglot built-in DataType canonicalization
    try:
        dt_a = exp.DataType.build(norm_a)
        dt_b = exp.DataType.build(norm_b)
        if dt_a.this == dt_b.this and dt_a.this != exp.DataType.Type.UNKNOWN:
            return True
    except Exception:
        pass

    # Check configured equivalent groups
    for eq_set in equivalent_types.values():
        if norm_a in eq_set and norm_b in eq_set:
            return True

    return False


class ModelTypeResolver:
    """Resolves table and column types from project models."""

    def __init__(self, models: dict[str, ModelRepresentation]) -> None:
        self._lookup: dict[str, dict[str, str]] = {}

        for name, model in models.items():
            if not model.columns_to_types:
                continue
            cols = {
                k.lower(): normalize_type_string(v)
                for k, v in model.columns_to_types.items()
            }
            clean_name = name.replace('"', "").lower()
            self._lookup[clean_name] = cols

            parts = clean_name.split(".")
            if len(parts) >= 2:
                self._lookup[".".join(parts[-2:])] = cols
            self._lookup[parts[-1]] = cols

    def find_column_type(self, table_node: exp.Table, col_name: str) -> str | None:
        """Find the resolved data type of col_name for the given Table expression."""
        t_name = (
            table_node.this.lower()
            if isinstance(table_node.this, str)
            else (table_node.name.lower() if table_node.this else "")
        )
        db = (
            table_node.db.lower()
            if isinstance(table_node.db, str)
            else (table_node.db.name.lower() if table_node.db else "")
        )
        cat = (
            table_node.catalog.lower()
            if isinstance(table_node.catalog, str)
            else (table_node.catalog.name.lower() if table_node.catalog else "")
        )

        candidates: list[str] = []
        if cat and db:
            candidates.append(f"{cat}.{db}.{t_name}")
        if db:
            candidates.append(f"{db}.{t_name}")
        candidates.append(t_name)

        clean_col = col_name.lower()
        for candidate in candidates:
            if candidate in self._lookup:
                cols = self._lookup[candidate]
                if clean_col in cols:
                    return cols[clean_col]
        return None

    def find_column_type_by_name(self, table_name: str, col_name: str) -> str | None:
        """Find the resolved data type given a table name string."""
        clean_tbl = table_name.replace('"', "").lower()
        clean_col = col_name.lower()

        if clean_tbl in self._lookup:
            return self._lookup[clean_tbl].get(clean_col)

        parts = clean_tbl.split(".")
        if len(parts) >= 2 and ".".join(parts[-2:]) in self._lookup:
            return self._lookup[".".join(parts[-2:])].get(clean_col)

        return self._lookup.get(parts[-1], {}).get(clean_col)


def resolve_expression_type(
    expr: exp.Expression,
    scope: Scope,
    resolver: ModelTypeResolver,
    depth: int = 0,
) -> str | None:
    """Infer or look up the data type of an expression in a given AST Scope."""
    if depth > 10:
        return None

    if isinstance(expr, exp.Cast):
        return normalize_type_string(expr.to.sql())

    if isinstance(expr, exp.Literal):
        if expr.is_string:
            return "text"
        if expr.is_number:
            return "integer" if expr.is_int else "float"

    if isinstance(expr, exp.Paren):
        return resolve_expression_type(expr.this, scope, resolver, depth + 1)

    if isinstance(expr, exp.Column):
        col_name = expr.name.lower()
        table_alias = expr.table.lower() if expr.table else None

        candidate_sources: list[exp.Table | Scope] = []
        if table_alias:
            src = scope.sources.get(table_alias)
            if src is not None:
                candidate_sources.append(src)
            else:
                for s_alias, s_val in scope.sources.items():
                    if s_alias.lower() == table_alias:
                        candidate_sources.append(s_val)
                        break
                    if isinstance(s_val, exp.Table) and s_val.name.lower() == table_alias:
                        candidate_sources.append(s_val)
                        break
        else:
            candidate_sources = list(scope.sources.values())

        for src in candidate_sources:
            if isinstance(src, exp.Table):
                col_type = resolver.find_column_type(src, col_name)
                if col_type:
                    return col_type
            elif isinstance(src, Scope) and hasattr(src.expression, "selects"):
                for sel in src.expression.selects:
                    if sel.alias_or_name.lower() == col_name:
                        inner = sel.this if isinstance(sel, exp.Alias) else sel
                        col_type = resolve_expression_type(inner, src, resolver, depth + 1)
                        if col_type:
                            return col_type
        return None

    return None


def collect_join_type_parity_findings(
    models: dict[str, ModelRepresentation],
    config: FitnessFunctionsConfig,
) -> list[LintFinding]:
    """Collect Connascence of Type (CoT) join parity findings across all eligible models."""
    rule_config = config.checks.join_type_parity
    if not rule_config.enabled:
        return []

    # Prepare configured equivalent type lookup
    equivalent_types: dict[str, set[str]] = {
        group: {normalize_type_string(t) for t in types}
        for group, types in (rule_config.equivalent_types or {}).items()
    }
    # Merge default equivalence groups for unconfigured categories
    for group, defaults in DEFAULT_EQUIVALENT_TYPES.items():
        if group not in equivalent_types:
            equivalent_types[group] = set(defaults)

    resolver = ModelTypeResolver(models)
    findings: list[LintFinding] = []

    for model in models.values():
        if model.is_external or model.is_symbolic:
            continue

        layer = get_layer_from_path(model.path, layer_order=config.layers.order)
        if not rule_config.should_run(layer):
            continue

        parsed = model.ast
        if parsed is None:
            continue

        seen_violations: set[str] = set()

        try:
            scopes = list(traverse_scope(parsed))
        except Exception:
            scopes = []

        if not scopes:
            # Fallback: search joins directly on the parsed expression
            main_joins = parsed.find_all(exp.Join)
            dummy_scope = Scope(parsed)
            for j in main_joins:
                _check_join_node(
                    j, dummy_scope, resolver, equivalent_types, model, rule_config.severity, findings, seen_violations
                )
            continue

        for scope in scopes:
            joins = scope.expression.args.get("joins", [])
            for join in joins:
                _check_join_node(
                    join, scope, resolver, equivalent_types, model, rule_config.severity, findings, seen_violations
                )

    return findings


def _check_join_node(
    join: exp.Join,
    scope: Scope,
    resolver: ModelTypeResolver,
    equivalent_types: dict[str, set[str]],
    model: ModelRepresentation,
    severity: str,
    findings: list[LintFinding],
    seen_violations: set[str],
) -> None:
    """Inspect a single join node for type mismatches in ON and USING clauses."""
    # 1. Inspect ON conditions
    on_clause = join.args.get("on")
    if on_clause:
        for eq in on_clause.find_all(exp.EQ):
            left_type = resolve_expression_type(eq.this, scope, resolver)
            right_type = resolve_expression_type(eq.expression, scope, resolver)

            if left_type and right_type and not are_types_equivalent(left_type, right_type, equivalent_types):
                condition_str = eq.sql()
                violation_key = f"{condition_str}:{left_type}:{right_type}"
                if violation_key in seen_violations:
                    continue
                seen_violations.add(violation_key)

                message = (
                    f"Join condition '{condition_str}' compares '{eq.this.sql()}' ({left_type}) "
                    f"with '{eq.expression.sql()}' ({right_type}) of mismatching data types. "
                    "This introduces Connascence of Type (CoT) and may cause implicit casting overhead, "
                    "index scan degradation, or execution errors."
                )
                findings.append(
                    LintFinding(
                        check="join_type_parity",
                        severity="error" if severity == "error" else "warning",
                        model=model.name,
                        path=model_path_relative(model),
                        message=message,
                    )
                )

    # 2. Inspect USING conditions
    using_clause = join.args.get("using")
    if using_clause:
        right_table = join.this
        # Determine left candidate sources in scope
        left_sources = [
            src for alias, src in scope.sources.items()
            if src is not right_table and alias != (getattr(right_table, "alias", None) or getattr(right_table, "name", None))
        ]

        for ident in using_clause:
            col_name = ident.name.lower()
            right_type: str | None = None
            if isinstance(right_table, exp.Table):
                right_type = resolver.find_column_type(right_table, col_name)

            if not right_type:
                continue

            for left_src in left_sources:
                left_type: str | None = None
                if isinstance(left_src, exp.Table):
                    left_type = resolver.find_column_type(left_src, col_name)
                elif isinstance(left_src, Scope) and hasattr(left_src.expression, "selects"):
                    for sel in left_src.expression.selects:
                        if sel.alias_or_name.lower() == col_name:
                            inner = sel.this if isinstance(sel, exp.Alias) else sel
                            left_type = resolve_expression_type(inner, left_src, resolver)
                            break

                if left_type and not are_types_equivalent(left_type, right_type, equivalent_types):
                    left_repr = getattr(left_src, "name", "left_table") if isinstance(left_src, exp.Table) else "left_table"
                    right_repr = getattr(right_table, "name", "right_table") if isinstance(right_table, exp.Table) else "right_table"
                    violation_key = f"USING({col_name}):{left_type}:{right_type}"
                    if violation_key in seen_violations:
                        continue
                    seen_violations.add(violation_key)

                    message = (
                        f"Join USING ({col_name}) compares '{left_repr}.{col_name}' ({left_type}) "
                        f"with '{right_repr}.{col_name}' ({right_type}) of mismatching data types. "
                        "This introduces Connascence of Type (CoT) and may cause implicit casting overhead, "
                        "index scan degradation, or execution errors."
                    )
                    findings.append(
                        LintFinding(
                            check="join_type_parity",
                            severity="error" if severity == "error" else "warning",
                            model=model.name,
                            path=model_path_relative(model),
                            message=message,
                        )
                    )
