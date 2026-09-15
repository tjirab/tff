"""Utility functions for handling Jinja templates in SQL queries."""

from __future__ import annotations

import re


def _strip_sqlmesh_macros(sql: str) -> str:
    """Replace SQLMesh macros (@macro(...) or @macro) outside strings, quotes, and comments."""
    n = len(sql)
    i = 0
    spans: list[tuple[int, int]] = []

    while i < n:
        ch = sql[i]

        # 1. Line comment --
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            i += 2
            while i < n and sql[i] not in ("\r", "\n"):
                i += 1
            continue

        # 2. Block comment /* ... */
        if ch == "/" and i + 1 < n and sql[i + 1] == "*":
            i += 2
            while i < n and not (sql[i - 1] == "*" and sql[i] == "/"):
                i += 1
            if i < n:
                i += 1
            continue

        # 3. Dollar-quoted string $$ or $tag$...$tag$
        if ch == "$":
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            if j < n and sql[j] == "$":
                tag = sql[i : j + 1]
                end_pos = sql.find(tag, j + 1)
                if end_pos != -1:
                    i = end_pos + len(tag)
                    continue

        # 4. Single-quoted string '...'
        if ch == "'":
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":  # escaped ''
                        i += 2
                        continue
                    i += 1
                    break
                elif sql[i] == "\\" and i + 1 < n:  # escaped \'
                    i += 2
                else:
                    i += 1
            continue

        # 5. Double-quoted identifier/string "..."
        if ch == '"':
            i += 1
            while i < n:
                if sql[i] == '"':
                    if i + 1 < n and sql[i + 1] == '"':  # escaped ""
                        i += 2
                        continue
                    i += 1
                    break
                elif sql[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            continue

        # 6. Backtick identifier `...`
        if ch == "`":
            i += 1
            while i < n:
                if sql[i] == "`":
                    if i + 1 < n and sql[i + 1] == "`":
                        i += 2
                        continue
                    i += 1
                    break
                elif sql[i] == "\\" and i + 1 < n:
                    i += 2
                else:
                    i += 1
            continue

        # 7. Bracket identifier [...]
        if ch == "[":
            i += 1
            while i < n and sql[i] != "]":
                i += 1
            if i < n:
                i += 1
            continue

        # 8. Check for SQLMesh macro starting with @
        if ch == "@":
            # Ensure not preceded by identifier char (e.g. not user@domain)
            if i > 0 and (sql[i - 1].isalnum() or sql[i - 1] == "_"):
                i += 1
                continue

            # Check if immediately followed by an identifier character
            if i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_"):
                start_macro = i
                i += 1
                while i < n and (sql[i].isalnum() or sql[i] == "_"):
                    i += 1

                # Check if followed by ( for macro call
                k = i
                while k < n and sql[k] in (" ", "\t"):
                    k += 1
                if k < n and sql[k] == "(":
                    depth = 1
                    k += 1
                    in_str = None
                    while k < n and depth > 0:
                        c = sql[k]
                        if in_str:
                            if c == in_str:
                                if k + 1 < n and sql[k + 1] == in_str:
                                    k += 2
                                    continue
                                in_str = None
                            elif c == "\\" and k + 1 < n:
                                k += 2
                                continue
                        elif c in ("'", '"', "`"):
                            in_str = c
                        elif c == "(":
                            depth += 1
                        elif c == ")":
                            depth -= 1
                        k += 1
                    if depth == 0:
                        spans.append((start_macro, k))
                        i = k
                        continue
                spans.append((start_macro, i))
                continue

        i += 1

    if not spans:
        return sql

    res = list(sql)
    for start, end in reversed(spans):
        res[start:end] = list(" __sqlmesh_macro__ ")
    return "".join(res)


def clean_jinja_for_parsing(sql: str, provider: str | None = None) -> str:
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

    # 6. Replace SQLMesh macros with dummy identifier (skip for dbt/dataform providers)
    if provider not in ("dbt", "dataform"):
        sql = _strip_sqlmesh_macros(sql)

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

