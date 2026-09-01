"""Auto-fixing engine for tff lint violations."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING
import yaml
import sqlglot
from sqlglot import exp

if TYPE_CHECKING:
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


def fix_positional_clauses(sql: str, dialect: str) -> str:
    """Rewrite positional GROUP BY and ORDER BY integers to explicit columns."""
    from sqlglot.dialects.dialect import Dialect
    resolved_dialect = None
    if dialect:
        try:
            Dialect.get_or_raise(dialect)
            resolved_dialect = dialect
        except ValueError:
            pass

    # 1. Extract the SQLMesh MODEL block if present
    model_block_match = re.match(r"^\s*(MODEL\s*\(.*?\)\s*;)", sql, flags=re.DOTALL | re.IGNORECASE)
    if model_block_match:
        model_block = model_block_match.group(1)
        query_part = sql[model_block_match.end():]
    else:
        model_block = ""
        query_part = sql
        
    # 2. Extract macros/Jinja to placeholders to prevent parsing errors
    patterns = [
        r"\{#.*?#\}",
        r"\{\{.*?\}\}",
        r"\{%.*?%\}",
        r"@\w+\([^)]*\)",
        r"@\w+",
    ]
    combined_pattern = re.compile("|".join(patterns), re.DOTALL)
    placeholders = {}
    
    def repl(match):
        idx = len(placeholders)
        ph = f"__TFF_MACRO_PH_{idx}__"
        placeholders[ph] = match.group(0)
        return ph
        
    temp_query = combined_pattern.sub(repl, query_part)
    
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
    for ph, orig in placeholders.items():
        modified_query = modified_query.replace(ph, orig)
        
    if model_block:
        return model_block + "\n\n" + modified_query
    return modified_query


def fix_sqlmesh_metadata(abs_path: Path, missing_owner: bool, missing_description: bool) -> str | None:
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


def fix_dbt_metadata(abs_path: Path, model_name: str, missing_owner: bool, missing_description: bool) -> str | None:
    """Scaffold or update metadata fields for a dbt model in its directory's schema file."""
    # Find any existing .yml/.yaml files in the same directory
    yaml_files = list(abs_path.parent.glob("*.yml")) + list(abs_path.parent.glob("*.yaml"))
    
    for yf in yaml_files:
        try:
            with open(yf, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            continue
            
        if not isinstance(data, dict) or "models" not in data or not isinstance(data["models"], list):
            continue
            
        # Look for the model entry
        model_entry = None
        for m in data["models"]:
            if isinstance(m, dict) and m.get("name") == model_name:
                model_entry = m
                break
                
        if model_entry is not None:
            modified = False
            if missing_description and ("description" not in model_entry or not model_entry["description"]):
                model_entry["description"] = "TODO: Add description"
                modified = True
            if missing_owner:
                if "meta" not in model_entry or not isinstance(model_entry["meta"], dict):
                    model_entry["meta"] = {}
                if "owner" not in model_entry["meta"] or not model_entry["meta"]["owner"]:
                    model_entry["meta"]["owner"] = "TODO: Add owner"
                    modified = True
                    
            if modified:
                try:
                    with open(yf, "w", encoding="utf-8") as f:
                        yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
                    return f"Updated metadata for model {model_name} in {yf.name}"
                except Exception as e:
                    return f"Failed to write dbt metadata to {yf.name}: {e}"
            return None

    # If the model entry was not found in any existing file, we append to schema.yml (or create it)
    schema_path = abs_path.parent / "schema.yml"
    is_new = not schema_path.exists()
    data = {}
    if not is_new:
        try:
            with open(schema_path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except Exception:
            pass
            
    if not isinstance(data, dict):
        data = {}
        
    if "version" not in data:
        data["version"] = 2
    if "models" not in data or not isinstance(data["models"], list):
        data["models"] = []
        
    model_entry = {"name": model_name}
    if missing_description:
        model_entry["description"] = "TODO: Add description"
    if missing_owner:
        model_entry["meta"] = {"owner": "TODO: Add owner"}
        
    data["models"].append(model_entry)
    
    try:
        with open(schema_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False)
        if is_new:
            return f"Scaffolded schema.yml for model {model_name}"
        return f"Appended metadata for model {model_name} to schema.yml"
    except Exception as e:
        return f"Failed to write/scaffold schema.yml in {abs_path.parent}: {e}"


def apply_autofixes(
    project_root: Path,
    provider: str,
    findings: list[LintFinding],
    models: dict[str, ModelRepresentation]
) -> list[str]:
    """Identify auto-fixable violations from findings and apply modifications to source files."""
    # Group findings by file path
    grouped = defaultdict(list)
    for f in findings:
        if f.path:
            abs_path = (project_root / f.path).resolve()
            grouped[abs_path].append(f)
            
    applied_logs = []
    
    for abs_path, file_findings in grouped.items():
        if not abs_path.exists():
            continue
            
        # 1. Fix positional group by / order by
        pos_findings = [f for f in file_findings if f.check == "nopositionalgroupbyororderby"]
        if pos_findings and abs_path.suffix == ".sql":
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
                    applied_logs.append(f"Fixed positional GROUP BY/ORDER BY in {abs_path.name}")
            except Exception as e:
                applied_logs.append(f"Failed to fix positional references in {abs_path.name}: {e}")
                
        # 2. Fix metadata issues (owner, description)
        missing_owner = any(f.check == "nomissingowner" for f in file_findings)
        missing_description = any(f.check == "nomissingdescription" for f in file_findings)
        
        if missing_owner or missing_description:
            model_name = file_findings[0].model
            if model_name:
                if provider == "sqlmesh":
                    log = fix_sqlmesh_metadata(abs_path, missing_owner, missing_description)
                    if log:
                        applied_logs.append(log)
                elif provider == "dbt":
                    log = fix_dbt_metadata(abs_path, model_name, missing_owner, missing_description)
                    if log:
                        applied_logs.append(log)
                        
    return applied_logs
