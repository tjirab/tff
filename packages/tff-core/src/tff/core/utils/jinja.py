"""Utility functions for handling Jinja templates in SQL queries."""

from __future__ import annotations

import re


def clean_jinja_for_parsing(sql: str) -> str:
    """Strip or replace raw Jinja blocks and macros to make SQL query text parseable by SQLGlot.

    Maps common references (like ref and source) to their model/table name placeholders
    so the query structure is preserved.
    """
    # 1. Remove Jinja comments
    sql = re.sub(r"\{#.*?#\}", "", sql, flags=re.DOTALL)

    # 2. Map dbt ref(...) to model name
    # e.g. {{ ref('my_model') }} -> my_model
    # e.g. {{ ref('package', 'my_model') }} -> my_model
    sql = re.sub(
        r"\{\{\s*ref\(\s*(?:['\"][^'\"]+['\"]\s*,\s*)?['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
        r" \1 ",
        sql,
    )

    # 3. Map dbt source(...) to table name
    # e.g. {{ source('my_source', 'my_table') }} -> my_table
    sql = re.sub(
        r"\{\{\s*source\(\s*['\"][^'\"]+['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}\}",
        r" \1 ",
        sql,
    )

    # 4. Replace other Jinja expression blocks {{ ... }} with a dummy identifier
    sql = re.sub(r"\{\{.*?\}\}", " __jinja_var__ ", sql, flags=re.DOTALL)

    # 5. Replace Jinja statement blocks {% ... %} with a space
    sql = re.sub(r"\{%.*?%\}", " ", sql, flags=re.DOTALL)

    # 6. Replace SQLMesh macros with dummy identifier
    sql = re.sub(r"@\w+\([^)]*\)", " __sqlmesh_macro__ ", sql)
    sql = re.sub(r"@\w+", " __sqlmesh_macro__ ", sql)

    return sql


def _strip_balanced_block(text: str, keyword: str) -> str:
    pattern = re.compile(rf"(?:^|\s){keyword}\s*\{{", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return text

    start = match.start()
    brace_start = match.end() - 1
    depth = 0
    in_quote = None
    end = -1

    for i in range(brace_start, len(text)):
        ch = text[i]
        if in_quote:
            if ch == "\\" and i + 1 < len(text):
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"', "`"):
            in_quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end != -1:
        remaining = text[:start] + " " + text[end:]
        return _strip_balanced_block(remaining, keyword)
    return text


def clean_dataform_for_parsing(sql: str) -> str:
    """Strip or replace Dataform-specific blocks and ${...} expressions to make SQL parseable by SQLGlot."""
    # 1. Remove config { ... } block if present
    sql = _strip_balanced_block(sql, "config")

    # 2. Remove js { ... } blocks
    sql = _strip_balanced_block(sql, "js")

    # 3. Remove pre_operations and post_operations blocks
    sql = _strip_balanced_block(sql, "pre_operations")
    sql = _strip_balanced_block(sql, "post_operations")

    # 4. Map ${ref("model")} or ${ref("schema", "model")}
    sql = re.sub(
        r"\$\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}",
        r" \1.\2 ",
        sql,
    )
    sql = re.sub(
        r"\$\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}",
        r" \1 ",
        sql,
    )
    sql = re.sub(
        r"\$\{\s*ref\(\s*\{[^}]*name\s*:\s*['\"]([^'\"]+)['\"][^}]*\}\s*\)\s*\}",
        r" \1 ",
        sql,
    )

    # 5. Map ${resolve("table")}
    sql = re.sub(
        r"\$\{\s*resolve\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}",
        r" \1 ",
        sql,
    )

    # 6. Replace remaining ${...} interpolations with dummy identifier
    sql = re.sub(r"\$\{.*?\}", " __dataform_var__ ", sql, flags=re.DOTALL)

    return sql

