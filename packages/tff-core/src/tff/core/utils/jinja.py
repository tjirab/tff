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
