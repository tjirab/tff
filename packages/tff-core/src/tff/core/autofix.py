"""Auto-fixing engine for tff lint violations."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any
from ruamel.yaml import YAML
import sqlglot
from sqlglot import exp

from tff.core.report import normalize_model_name

if TYPE_CHECKING:
    from tff.core.adapter import PipelineAdapter
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding


def parse_model_block_args(block_text: str) -> list[tuple[str, str]]:
    """Parse the arguments inside a SQLMesh MODEL(...) block.
    Returns a list of (key, value) pairs.
    """
    pairs = []
    current = []
    in_quotes = None
    depth = 0

    # Split by top-level commas
    for char in block_text:
        if char in ("'", '"'):
            if in_quotes == char:
                in_quotes = None
            elif in_quotes is None:
                in_quotes = char
            current.append(char)
        elif char == "(" and in_quotes is None:
            depth += 1
            current.append(char)
        elif char == ")" and in_quotes is None:
            depth -= 1
            current.append(char)
        elif char == "," and in_quotes is None and depth == 0:
            pairs.append("".join(current).strip())
            current = []
        else:
            current.append(char)
    if current:
        pairs.append("".join(current).strip())

    parsed_pairs = []
    for pair in pairs:
        if not pair:
            continue
        parts = pair.split(None, 1)
        if len(parts) == 2:
            parsed_pairs.append((parts[0], parts[1]))
        else:
            parsed_pairs.append((pair, ""))
    return parsed_pairs


def _resolve_dialect(dialect: str) -> str | None:
    """Resolve and validate a dialect string for sqlglot."""
    from sqlglot.dialects.dialect import Dialect

    if dialect:
        try:
            Dialect.get_or_raise(dialect)
            return dialect
        except ValueError:
            pass
    return None


def _extract_model_or_config_block(sql: str) -> tuple[str, str]:
    """Extract SQLMesh MODEL or Dataform config block if present, returning (block, query_part)."""
    model_block_match = re.match(
        r"^\s*(MODEL\s*\(.*?\)\s*;)", sql, flags=re.DOTALL | re.IGNORECASE
    )
    config_match = re.search(
        r"^\s*config\s*\{", sql, flags=re.MULTILINE | re.IGNORECASE
    )
    if model_block_match:
        model_block = model_block_match.group(1)
        query_part = sql[model_block_match.end() :]
    elif config_match:
        brace_start = config_match.end() - 1
        depth = 0
        in_quote = None
        end = -1
        for i in range(brace_start, len(sql)):
            ch = sql[i]
            if in_quote:
                if ch == "\\" and i + 1 < len(sql):
                    continue
                if ch == in_quote:
                    in_quote = None
            elif ch in ('"', "'", "`"):
                in_quote = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end != -1:
            model_block = sql[:end].strip()
            query_part = sql[end:]
        else:
            model_block = ""
            query_part = sql
    else:
        model_block = ""
        query_part = sql
    return model_block, query_part


_MACRO_PATTERNS = [
    r"\{#.*?#\}",
    r"\{\{.*?\}\}",
    r"\{%.*?%\}",
    r"@\w+\([^)]*\)",
    r"@\w+",
    r"\$\{.*?\}",
]
_MACRO_COMBINED_PATTERN = re.compile("|".join(_MACRO_PATTERNS), re.DOTALL)


def _mask_macros(query: str) -> tuple[str, dict[str, str]]:
    """Replace macros/Jinja with unique placeholder tokens to prevent SQL parsing errors."""
    placeholders: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        idx = len(placeholders)
        ph = f"__TFF_MACRO_PH_{idx}__"
        placeholders[ph] = match.group(0)
        return ph

    return _MACRO_COMBINED_PATTERN.sub(repl, query), placeholders


def _unmask_macros(query: str, placeholders: dict[str, str]) -> str:
    """Restore macro/Jinja placeholders back to their original strings."""
    for ph, orig in placeholders.items():
        query = query.replace(ph, orig)
    return query


def fix_positional_clauses(sql: str, dialect: str) -> str:
    """Rewrite positional GROUP BY and ORDER BY integers to explicit columns."""
    resolved_dialect = _resolve_dialect(dialect)

    # 1. Extract the SQLMesh MODEL or Dataform config block if present
    model_block, query_part = _extract_model_or_config_block(sql)

    # 2. Extract macros/Jinja to placeholders to prevent parsing errors
    temp_query, placeholders = _mask_macros(query_part)

    # 3. Parse with sqlglot
    try:
        parsed = sqlglot.parse_one(temp_query, read=resolved_dialect)
    except Exception:
        # If parsing fails, we cannot auto-fix this file
        return sql

    # 4. AST modification
    modified = False
    for select in parsed.find_all(exp.Select):
        selects = select.selects

        group = select.args.get("group")
        if group:
            new_group_expressions = []
            for expr in group.expressions:
                if isinstance(expr, exp.Literal) and expr.is_int:
                    val = int(expr.this)
                    if 1 <= val <= len(selects):
                        select_expr = selects[val - 1]
                        modified = True
                        if isinstance(select_expr, exp.Alias):
                            new_group_expressions.append(exp.column(select_expr.alias))
                        else:
                            new_group_expressions.append(select_expr.copy())
                    else:
                        new_group_expressions.append(expr)
                else:
                    new_group_expressions.append(expr)
            group.set("expressions", new_group_expressions)

        order = select.args.get("order")
        if order:
            for ordered in order.expressions:
                if isinstance(ordered.this, exp.Literal) and ordered.this.is_int:
                    val = int(ordered.this.this)
                    if 1 <= val <= len(selects):
                        select_expr = selects[val - 1]
                        modified = True
                        if isinstance(select_expr, exp.Alias):
                            ordered.set("this", exp.column(select_expr.alias))
                        else:
                            ordered.set("this", select_expr.copy())

    if not modified:
        return sql

    # 5. Format back and restore placeholders
    modified_query = parsed.sql(dialect=resolved_dialect)
    modified_query = _unmask_macros(modified_query, placeholders)

    if model_block:
        return model_block + "\n\n" + modified_query
    return modified_query


def lift_nested_subqueries(sql: str, dialect: str) -> str:
    """Refactor nested subqueries in FROM and JOIN clauses of the final SELECT into named CTEs."""
    resolved_dialect = _resolve_dialect(dialect)
    model_block, query_part = _extract_model_or_config_block(sql)
    temp_query, placeholders = _mask_macros(query_part)

    try:
        parsed = sqlglot.parse_one(temp_query, read=resolved_dialect)
    except Exception:
        return sql

    final_select = parsed.this if isinstance(parsed, exp.With) else parsed
    if not isinstance(final_select, exp.Select):
        return sql

    from_clause = final_select.args.get("from_") or final_select.args.get("from")
    joins = final_select.args.get("joins") or []

    subqueries_to_lift: list[exp.Subquery] = []
    if (
        from_clause
        and isinstance(from_clause.this, exp.Subquery)
        and isinstance(from_clause.this.this, exp.Query)
    ):
        subqueries_to_lift.append(from_clause.this)

    for join in joins:
        if isinstance(join.this, exp.Subquery) and isinstance(
            join.this.this, exp.Query
        ):
            subqueries_to_lift.append(join.this)

    if not subqueries_to_lift:
        return sql

    with_clause = (
        parsed
        if isinstance(parsed, exp.With)
        else (final_select.args.get("with_") or final_select.args.get("with"))
    )
    existing_cte_names: set[str] = set()
    if with_clause:
        for cte in with_clause.expressions:
            if cte.alias:
                existing_cte_names.add(cte.alias.lower())

    new_ctes: list[exp.CTE] = []
    extracted_counter = 1

    for sub in subqueries_to_lift:
        orig_alias = sub.alias
        if not orig_alias:
            while f"__extracted_cte_{extracted_counter}".lower() in existing_cte_names:
                extracted_counter += 1
            alias = f"__extracted_cte_{extracted_counter}"
            extracted_counter += 1
        elif orig_alias.lower() in existing_cte_names:
            base = orig_alias
            idx = 1
            while f"{base}_{idx}".lower() in existing_cte_names:
                idx += 1
            alias = f"{base}_{idx}"
        else:
            alias = orig_alias

        existing_cte_names.add(alias.lower())

        alias_node = sub.args.get("alias")
        if alias_node and alias_node.this and alias_node.name == alias:
            cte_alias = alias_node.copy()
        else:
            cte_alias = exp.TableAlias(this=exp.to_identifier(alias))

        cte = exp.CTE(this=sub.this.copy(), alias=cte_alias)
        new_ctes.append(cte)

        if orig_alias and alias != orig_alias:
            table_node = exp.Table(
                this=exp.to_identifier(alias),
                alias=exp.TableAlias(this=exp.to_identifier(orig_alias)),
            )
        else:
            table_node = exp.Table(this=exp.to_identifier(alias))

        sub.replace(table_node)

    if with_clause:
        for cte in new_ctes:
            with_clause.append("expressions", cte)
    else:
        final_select.set("with_", exp.With(expressions=new_ctes))

    modified_query = parsed.sql(dialect=resolved_dialect)
    modified_query = _unmask_macros(modified_query, placeholders)

    if model_block:
        return model_block + "\n\n" + modified_query
    return modified_query


def fix_sqlmesh_metadata(
    abs_path: Path, missing_owner: bool, missing_description: bool
) -> str | None:
    """Update metadata fields inside a SQLMesh MODEL block."""
    try:
        sql = abs_path.read_text(encoding="utf-8")
    except Exception:
        return None

    model_block_match = re.search(r"MODEL\s*\((.*?)\)", sql, re.DOTALL | re.IGNORECASE)
    if not model_block_match:
        return None

    args_str = model_block_match.group(1)
    args = parse_model_block_args(args_str)
    keys = {k.lower() for k, v in args}

    modified = False
    if missing_owner and "owner" not in keys:
        args.append(("owner", "'TODO: Add owner'"))
        modified = True
    if missing_description and "description" not in keys:
        args.append(("description", "'TODO: Add description'"))
        modified = True

    if not modified:
        return None

    formatted_args = [f"{k} {v}" for k, v in args]
    new_block = "MODEL (\n  " + ",\n  ".join(formatted_args) + "\n)"
    new_sql = sql.replace(model_block_match.group(0), new_block, 1)

    try:
        abs_path.write_text(new_sql, encoding="utf-8")
        return f"Added missing metadata to MODEL block in {abs_path.name}"
    except Exception as e:
        return f"Failed to write SQLMesh metadata for {abs_path.name}: {e}"


def _get_roundtrip_yaml() -> YAML:
    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    return yaml_rt


def fix_dbt_metadata(
    abs_path: Path, model_name: str, missing_owner: bool, missing_description: bool
) -> str | None:
    """Scaffold or update metadata fields for a dbt model in its directory's schema file,
    preserving comments, indentation, and key order using ruamel.yaml.
    """
    yaml_rt = _get_roundtrip_yaml()
    # Find any existing .yml/.yaml files in the same directory
    yaml_files = list(abs_path.parent.glob("*.yml")) + list(
        abs_path.parent.glob("*.yaml")
    )

    for yf in yaml_files:
        try:
            with open(yf, encoding="utf-8") as f:
                data = yaml_rt.load(f)
        except Exception:
            continue

        if (
            not isinstance(data, (dict, Mapping))
            or "models" not in data
            or not isinstance(data["models"], (list, Sequence))
        ):
            continue

        # Look for the model entry
        model_entry = None
        for m in data["models"]:
            if isinstance(m, (dict, Mapping)) and m.get("name") == model_name:
                model_entry = m
                break

        if model_entry is not None:
            modified = False
            if missing_description and (
                "description" not in model_entry or not model_entry["description"]
            ):
                model_entry["description"] = "TODO: Add description"
                modified = True
            if missing_owner:
                if "meta" not in model_entry or not isinstance(
                    model_entry["meta"], (dict, Mapping)
                ):
                    model_entry["meta"] = {}
                if (
                    "owner" not in model_entry["meta"]
                    or not model_entry["meta"]["owner"]
                ):
                    model_entry["meta"]["owner"] = "TODO: Add owner"
                    modified = True

            if modified:
                try:
                    with open(yf, "w", encoding="utf-8") as f:
                        yaml_rt.dump(data, f)
                    return f"Updated metadata for model {model_name} in {yf.name}"
                except Exception as e:
                    return f"Failed to write dbt metadata to {yf.name}: {e}"
            return None

    # If the model entry was not found in any existing file, we append to schema.yml (or create it)
    schema_path = abs_path.parent / "schema.yml"
    is_new = not schema_path.exists()
    data = None
    if not is_new:
        try:
            with open(schema_path, encoding="utf-8") as f:
                data = yaml_rt.load(f)
        except Exception:
            pass

    if not isinstance(data, (dict, Mapping)):
        data = {"version": 2, "models": []}

    if "version" not in data:
        data["version"] = 2
    if "models" not in data or not isinstance(data["models"], (list, Sequence)):
        data["models"] = []

    model_entry = {"name": model_name}
    if missing_description:
        model_entry["description"] = "TODO: Add description"
    if missing_owner:
        model_entry["meta"] = {"owner": "TODO: Add owner"}

    data["models"].append(model_entry)

    try:
        with open(schema_path, "w", encoding="utf-8") as f:
            yaml_rt.dump(data, f)
        if is_new:
            return f"Scaffolded schema.yml for model {model_name}"
        return f"Appended metadata for model {model_name} to schema.yml"
    except Exception as e:
        return f"Failed to write/scaffold schema.yml in {abs_path.parent}: {e}"


def _find_matching_brace(text: str, open_brace_idx: int) -> int:
    """Find the index of the matching closing brace '}' for the open brace at open_brace_idx."""
    if open_brace_idx < 0 or open_brace_idx >= len(text) or text[open_brace_idx] != "{":
        return -1
    depth = 0
    in_quote = None
    i = open_brace_idx
    length = len(text)
    while i < length:
        ch = text[i]
        if in_quote:
            if ch == "\\" and i + 1 < length:
                i += 2
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'", "`"):
            in_quote = ch
        elif ch == "/" and i + 1 < length and text[i + 1] == "/":
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            continue
        elif ch == "/" and i + 1 < length and text[i + 1] == "*":
            end_c = text.find("*/", i + 2)
            if end_c == -1:
                break
            i = end_c + 2
            continue
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def fix_dataform_metadata(
    abs_path: Path,
    missing_owner: bool,
    missing_description: bool,
    model_name: str | None = None,
) -> str | None:
    """Scaffold or update metadata fields (owner, description) in a Dataform .sqlx file."""
    if not missing_owner and not missing_description:
        return None

    if abs_path.suffix not in (".sqlx", ".sql") or not abs_path.exists() or abs_path.is_dir():
        return None

    try:
        content = abs_path.read_text(encoding="utf-8")
    except Exception:
        return None

    # Check for existing config { ... } block
    match = re.search(r"^\s*config\s*\{", content, re.MULTILINE | re.IGNORECASE)
    if not match:
        match = re.search(r"\bconfig\s*\{", content, re.IGNORECASE)

    if not match:
        # Scaffold a minimal config block header
        scaffold_lines = ["config {", '  type: "view",']
        if missing_description and missing_owner:
            scaffold_lines.append('  description: "TODO: Add description",')
            scaffold_lines.append("  bigquery: {")
            scaffold_lines.append("    labels: {")
            scaffold_lines.append('      owner: "TODO: Add owner"')
            scaffold_lines.append("    }")
            scaffold_lines.append("  }")
        elif missing_description:
            scaffold_lines.append('  description: "TODO: Add description"')
        elif missing_owner:
            scaffold_lines.append("  bigquery: {")
            scaffold_lines.append("    labels: {")
            scaffold_lines.append('      owner: "TODO: Add owner"')
            scaffold_lines.append("    }")
            scaffold_lines.append("  }")
        scaffold_lines.append("}")
        scaffold_str = "\n".join(scaffold_lines)

        stripped = content.strip()
        if stripped:
            new_content = scaffold_str + "\n\n" + stripped + "\n"
        else:
            new_content = scaffold_str + "\n"

        try:
            abs_path.write_text(new_content, encoding="utf-8")
            return f"Scaffolded config block in {abs_path.name}"
        except Exception as e:
            return f"Failed to write Dataform metadata for {abs_path.name}: {e}"

    # Existing config block found
    brace_start = match.end() - 1
    brace_end = _find_matching_brace(content, brace_start)
    if brace_end == -1:
        return None

    config_str = content[brace_start : brace_end + 1]

    # Parse what is currently configured
    from tff.dataform.manifest import _parse_sqlx_config

    parsed, _ = _parse_sqlx_config(content)

    has_desc = bool(parsed.get("description")) if isinstance(parsed, dict) else False
    if not has_desc:
        has_desc = bool(
            re.search(r'\bdescription\s*:\s*(["\'])(?!\1).+?\1', config_str)
        )

    has_owner = False
    if isinstance(parsed, dict):
        meta = parsed.get("bigquery", {}) or {}
        has_owner = bool(
            meta.get("labels", {}).get("owner")
            or meta.get("owner")
            or parsed.get("owner")
        )
    if not has_owner:
        has_owner = bool(
            re.search(r'\bowner\s*:\s*(["\'])(?!\1).+?\1', config_str)
        )

    need_desc = missing_description and not has_desc
    need_owner = missing_owner and not has_owner

    if not need_desc and not need_owner:
        return None

    # Handle empty string values if already present
    modified_config = config_str
    if need_desc and re.search(r'\bdescription\s*:\s*(["\'])\s*\1', modified_config):
        modified_config = re.sub(
            r'(\bdescription\s*:\s*)(["\'])\s*\2',
            r'\1"TODO: Add description"',
            modified_config,
            count=1,
        )
        need_desc = False

    if need_owner and re.search(r'\bowner\s*:\s*(["\'])\s*\1', modified_config):
        modified_config = re.sub(
            r'(\bowner\s*:\s*)(["\'])\s*\2',
            r'\1"TODO: Add owner"',
            modified_config,
            count=1,
        )
        need_owner = False

    if not need_desc and not need_owner:
        new_content = content[:brace_start] + modified_config + content[brace_end + 1 :]
        try:
            abs_path.write_text(new_content, encoding="utf-8")
            return f"Added missing metadata to config block in {abs_path.name}"
        except Exception as e:
            return f"Failed to write Dataform metadata for {abs_path.name}: {e}"

    # Determine indentation
    indent = "  "
    for line in modified_config.splitlines()[1:]:
        m = re.match(r"^(\s+)\S", line)
        if m:
            indent = m.group(1)
            break

    # If owner needed, check if bigquery: { ... } already exists
    bq_match = re.search(r"\bbigquery\s*:\s*\{", modified_config)
    if need_owner and bq_match:
        bq_brace_start = bq_match.end() - 1
        bq_brace_end = _find_matching_brace(modified_config, bq_brace_start)
        if bq_brace_end != -1:
            bq_inner = modified_config[bq_brace_start : bq_brace_end + 1]
            labels_match = re.search(r"\blabels\s*:\s*\{", bq_inner)
            if labels_match:
                lbl_brace_start = bq_brace_start + labels_match.end() - 1
                lbl_brace_end = _find_matching_brace(modified_config, lbl_brace_start)
                if lbl_brace_end != -1:
                    lbl_nl = modified_config.find("\n", lbl_brace_start, lbl_brace_end)
                    if lbl_nl != -1:
                        insert_at = lbl_nl + 1
                        injection = f'{indent * 3}owner: "TODO: Add owner",\n'
                    else:
                        insert_at = lbl_brace_start + 1
                        injection = ' owner: "TODO: Add owner", '
                    modified_config = (
                        modified_config[:insert_at]
                        + injection
                        + modified_config[insert_at:]
                    )
                    need_owner = False
            else:
                bq_nl = modified_config.find("\n", bq_brace_start, bq_brace_end)
                if bq_nl != -1:
                    insert_at = bq_nl + 1
                    injection = (
                        f"{indent * 2}labels: {{\n"
                        f'{indent * 3}owner: "TODO: Add owner"\n'
                        f"{indent * 2}}},\n"
                    )
                else:
                    insert_at = bq_brace_start + 1
                    injection = ' labels: { owner: "TODO: Add owner" }, '
                modified_config = (
                    modified_config[:insert_at]
                    + injection
                    + modified_config[insert_at:]
                )
                need_owner = False

    fields_to_inject = []
    if need_desc:
        fields_to_inject.append(f'{indent}description: "TODO: Add description",\n')
    if need_owner:
        fields_to_inject.append(
            f"{indent}bigquery: {{\n"
            f"{indent * 2}labels: {{\n"
            f'{indent * 3}owner: "TODO: Add owner"\n'
            f"{indent * 2}}}\n"
            f"{indent}}},\n"
        )

    if fields_to_inject:
        nl_idx = modified_config.find("\n")
        inner_content = modified_config[1:-1].strip()
        if not inner_content:
            cleaned_injection = "".join(fields_to_inject).rstrip()
            if cleaned_injection.endswith(","):
                cleaned_injection = cleaned_injection[:-1]
            modified_config = "{\n" + cleaned_injection + "\n}"
        elif nl_idx != -1:
            insert_at = nl_idx + 1
            modified_config = (
                modified_config[:insert_at]
                + "".join(fields_to_inject)
                + modified_config[insert_at:]
            )
        else:
            modified_config = (
                "{\n"
                + "".join(fields_to_inject)
                + indent
                + modified_config[1:-1].strip()
                + "\n}"
            )

    new_content = content[:brace_start] + modified_config + content[brace_end + 1 :]
    try:
        abs_path.write_text(new_content, encoding="utf-8")
        return f"Added missing metadata to config block in {abs_path.name}"
    except Exception as e:
        return f"Failed to write Dataform metadata for {abs_path.name}: {e}"



def expand_select_star(
    sql: str,
    dialect: str = "ansi",
    models: Mapping[str, Any] | None = None,
    model_name: str | None = None,
) -> tuple[str, list[str]]:
    """Expand SELECT * and table.* into explicit column projections when upstream schema is known.

    Returns:
        tuple[str, list[str]]: (modified_sql, list_of_warnings).
        If any table's schema cannot be resolved statically, the original SQL is returned unmodified
        along with a warning string.
    """
    resolved_dialect = _resolve_dialect(dialect)
    model_block, query_part = _extract_model_or_config_block(sql)
    temp_query, placeholders = _mask_macros(query_part)

    try:
        parsed = sqlglot.parse_one(temp_query, read=resolved_dialect)
    except Exception:
        return sql, []

    # Check if any star exists that is not COUNT(*) or aggregate
    has_star = False
    for star in parsed.find_all(exp.Star):
        if (
            isinstance(star.parent, (exp.Count, exp.Distinct))
            and star.find_ancestor(exp.Count) is not None
        ):
            continue
        has_star = True
        break
    if not has_star:
        return sql, []

    def _extract_columns(entry: Any) -> list[str] | None:
        if hasattr(entry, "columns_to_types") and entry.columns_to_types:
            return list(entry.columns_to_types.keys())
        if isinstance(entry, dict) and entry:
            return list(entry.keys())
        if isinstance(entry, (list, tuple, set)) and entry:
            return list(entry)
        return None

    def _clean_table_display_name(raw_name: str) -> str:
        if raw_name in placeholders:
            ph_val = placeholders[raw_name]
            m = re.search(
                r"(?:ref|source)\s*\(\s*(?:['\"][^'\"]+['\"]\s*,\s*)?['\"]([^'\"]+)['\"]\s*\)",
                ph_val,
            )
            if m:
                return m.group(1)
            return ph_val
        return raw_name

    def _get_model_columns(table_name: str, db: str | None = None) -> list[str] | None:
        if not models:
            return None
        cand_names = [f"{db}.{table_name}", table_name] if db else [table_name]
        if table_name in placeholders:
            ph_val = placeholders[table_name]
            m = re.search(
                r"(?:ref|source)\s*\(\s*(?:['\"][^'\"]+['\"]\s*,\s*)?['\"]([^'\"]+)['\"]\s*\)",
                ph_val,
            )
            if m:
                cand_names.insert(0, m.group(1))

        for cand in cand_names:
            for k, v in models.items():
                if k.lower() == cand.lower():
                    cols = _extract_columns(v)
                    if cols:
                        return cols
            for v in models.values():
                v_name = getattr(v, "name", None)
                if not v_name:
                    continue
                if v_name.lower() == cand.lower():
                    cols = _extract_columns(v)
                    if cols:
                        return cols
                if (
                    normalize_model_name(v_name).lower()
                    == normalize_model_name(cand).lower()
                ):
                    cols = _extract_columns(v)
                    if cols:
                        return cols
                if v_name.split(".")[-1].lower() == cand.split(".")[-1].lower():
                    cols = _extract_columns(v)
                    if cols:
                        return cols
        return None

    cte_schemas: dict[str, list[str]] = {}

    def _get_source_columns(
        src: exp.Expression,
    ) -> tuple[list[str] | None, str, str]:
        if isinstance(src, exp.Subquery):
            alias = src.alias or ""
            cols = (
                [s.alias_or_name for s in src.this.selects]
                if isinstance(src.this, exp.Select)
                else None
            )
            return cols, alias or "subquery", alias or "subquery"
        if isinstance(src, exp.Table):
            t_name = src.name
            t_alias = src.alias or ""
            qualifier = t_alias or t_name
            disp_name = _clean_table_display_name(t_name)
            if t_name.lower() in cte_schemas:
                return cte_schemas[t_name.lower()], qualifier, disp_name
            cols = _get_model_columns(t_name, src.db or None)
            return cols, qualifier, disp_name
        return None, "", "unknown"

    def _expand_select(select_node: exp.Select) -> str | None:
        nonlocal modified
        from_clause = select_node.args.get("from_") or select_node.args.get(
            "from"
        )
        joins = select_node.args.get("joins") or []
        sources = []
        if from_clause and from_clause.this:
            sources.append(from_clause.this)
        for j in joins:
            if j.this:
                sources.append(j.this)

        # Check if select has star to expand
        has_sel_star = any(
            isinstance(s, exp.Star)
            or (isinstance(s, exp.Column) and isinstance(s.this, exp.Star))
            for s in select_node.selects
        )
        if not has_sel_star:
            return None

        new_selects = []
        for s in select_node.selects:
            if isinstance(s, exp.Star):
                if not sources:
                    return (
                        f"Skipped SELECT * expansion for {model_name or 'model'}: "
                        "upstream schema is not available statically"
                    )
                if len(sources) == 1:
                    cols, qual, disp = _get_source_columns(sources[0])
                    if cols is None:
                        return (
                            f"Skipped SELECT * expansion for {model_name or 'model'}: "
                            f"upstream schema for {disp} is not available statically"
                        )
                    new_selects.extend([exp.column(c) for c in cols])
                else:
                    for src in sources:
                        cols, qual, disp = _get_source_columns(src)
                        if cols is None:
                            return (
                                f"Skipped SELECT * expansion for {model_name or 'model'}: "
                                f"upstream schema for {disp} is not available statically"
                            )
                        new_selects.extend(
                            [exp.column(c, table=qual) for c in cols]
                        )
                modified = True
            elif isinstance(s, exp.Column) and isinstance(s.this, exp.Star):
                tbl_target = s.table
                matched_src = None
                for src in sources:
                    if isinstance(src, exp.Table):
                        if (
                            src.alias and src.alias.lower() == tbl_target.lower()
                        ) or (
                            src.name and src.name.lower() == tbl_target.lower()
                        ):
                            matched_src = src
                            break
                    elif isinstance(src, exp.Subquery):
                        if src.alias and src.alias.lower() == tbl_target.lower():
                            matched_src = src
                            break
                if not matched_src:
                    return (
                        f"Skipped SELECT * expansion for {model_name or 'model'}: "
                        f"upstream schema for {tbl_target} is not available statically"
                    )
                cols, qual, disp = _get_source_columns(matched_src)
                if cols is None:
                    return (
                        f"Skipped SELECT * expansion for {model_name or 'model'}: "
                        f"upstream schema for {disp} is not available statically"
                    )
                new_selects.extend(
                    [exp.column(c, table=tbl_target) for c in cols]
                )
                modified = True
            else:
                new_selects.append(s)

        select_node.set("expressions", new_selects)
        return None

    modified = False

    # 1. Process CTEs in sequential order
    with_clause = (
        parsed
        if isinstance(parsed, exp.With)
        else (parsed.args.get("with_") or parsed.args.get("with"))
    )
    if with_clause:
        for cte in with_clause.expressions:
            for s_node in reversed(list(cte.this.find_all(exp.Select))):
                err = _expand_select(s_node)
                if err:
                    return sql, [err]
            if cte.args.get("alias") and cte.args["alias"].args.get("columns"):
                cte_schemas[cte.alias.lower()] = [
                    c.name
                    for c in cte.args["alias"].args.get("columns", [])
                ]
            elif isinstance(cte.this, exp.Select):
                cte_schemas[cte.alias.lower()] = [
                    s.alias_or_name for s in cte.this.selects
                ]

    # 2. Process non-CTE selects bottom-up
    for s_node in reversed(list(parsed.find_all(exp.Select))):
        if s_node.find_ancestor(exp.CTE) is not None:
            continue
        err = _expand_select(s_node)
        if err:
            return sql, [err]

    if not modified:
        return sql, []

    modified_query = parsed.sql(dialect=resolved_dialect)
    modified_query = _unmask_macros(modified_query, placeholders)
    if model_block:
        return model_block + "\n\n" + modified_query, []
    return modified_query, []


def apply_autofixes(
    project_root: Path | Sequence[Path],
    provider: str | PipelineAdapter,
    findings: list[LintFinding],
    models: dict[str, ModelRepresentation],
) -> list[str]:
    """Identify auto-fixable violations from findings and apply modifications to source files."""
    from tff.core.adapter import get_adapter, normalize_project_roots

    if isinstance(provider, str):
        adapter = get_adapter(provider)
    else:
        adapter = provider

    roots = normalize_project_roots(project_root)

    # Group findings by file path
    grouped = defaultdict(list)
    for f in findings:
        if f.path:
            p = Path(f.path)
            if p.is_absolute():
                abs_path = p.resolve()
            else:
                abs_path = (roots[0] / f.path).resolve()
                for r in roots:
                    cand = (r / f.path).resolve()
                    if cand.exists():
                        abs_path = cand
                        break
            grouped[abs_path].append(f)

    applied_logs = []

    for abs_path, file_findings in grouped.items():
        if not abs_path.exists():
            continue

        # 1. Fix positional group by / order by
        pos_findings = [
            f for f in file_findings if f.check == "nopositionalgroupbyororderby"
        ]
        if pos_findings and abs_path.suffix in (".sql", ".sqlx"):
            # Lookup dialect from models dictionary
            dialect = "ansi"
            for model in models.values():
                if Path(model.path).resolve() == abs_path:
                    dialect = model.dialect
                    break

            try:
                sql = abs_path.read_text(encoding="utf-8")
                fixed_sql = fix_positional_clauses(sql, dialect)
                if fixed_sql != sql:
                    abs_path.write_text(fixed_sql, encoding="utf-8")
                    applied_logs.append(
                        f"Fixed positional GROUP BY/ORDER BY in {abs_path.name}"
                    )
            except Exception as e:
                applied_logs.append(
                    f"Failed to fix positional references in {abs_path.name}: {e}"
                )

        # 2. Fix nested subqueries in final SELECT
        subquery_findings = [
            f
            for f in file_findings
            if f.check == "sqlcomplexity"
            and "nested subquery in final SELECT" in f.message
        ]
        if subquery_findings and abs_path.suffix in (".sql", ".sqlx"):
            dialect = "ansi"
            for model in models.values():
                if Path(model.path).resolve() == abs_path:
                    dialect = model.dialect
                    break

            try:
                sql = abs_path.read_text(encoding="utf-8")
                fixed_sql = lift_nested_subqueries(sql, dialect)
                if fixed_sql != sql:
                    abs_path.write_text(fixed_sql, encoding="utf-8")
                    applied_logs.append(
                        f"Refactored nested subqueries in final SELECT to CTEs in {abs_path.name}"
                    )
            except Exception as e:
                applied_logs.append(
                    f"Failed to refactor nested subqueries in {abs_path.name}: {e}"
                )

        # 3. Fix SELECT * (banselectstar)
        star_findings = [
            f
            for f in file_findings
            if f.check in ("banselectstar", "ban_select_star")
        ]
        if star_findings and abs_path.suffix in (".sql", ".sqlx"):
            dialect = "ansi"
            model_name = file_findings[0].model if file_findings else None
            for model in models.values():
                if Path(model.path).resolve() == abs_path:
                    dialect = model.dialect
                    if not model_name:
                        model_name = model.name
                    break

            try:
                sql = abs_path.read_text(encoding="utf-8")
                fixed_sql, warnings = expand_select_star(
                    sql,
                    dialect=dialect,
                    models=models,
                    model_name=model_name,
                )
                if warnings:
                    applied_logs.extend(warnings)
                elif fixed_sql != sql:
                    abs_path.write_text(fixed_sql, encoding="utf-8")
                    applied_logs.append(f"Expanded SELECT * in {abs_path.name}")
            except Exception as e:
                applied_logs.append(
                    f"Failed to expand SELECT * in {abs_path.name}: {e}"
                )

        # 4. Fix metadata issues (owner, description)
        missing_owner = any(f.check == "nomissingowner" for f in file_findings)
        missing_description = any(
            f.check == "nomissingdescription" for f in file_findings
        )

        if missing_owner or missing_description:
            model_name = file_findings[0].model
            if model_name:
                matching_root = roots[0]
                for r in roots:
                    try:
                        abs_path.relative_to(r)
                        matching_root = r
                        break
                    except ValueError:
                        pass
                log = adapter.apply_metadata_fix(
                    project_root=matching_root,
                    abs_path=abs_path,
                    model_name=model_name,
                    missing_owner=missing_owner,
                    missing_description=missing_description,
                )
                if log:
                    applied_logs.append(log)

    return applied_logs
