from tff.core.utils.jinja import clean_jinja_for_parsing


def test_clean_jinja_comments() -> None:
    sql = "SELECT * FROM table {# this is a comment #}"
    cleaned = clean_jinja_for_parsing(sql)
    assert "this is a comment" not in cleaned
    assert "table" in cleaned


def test_clean_jinja_ref_single_arg() -> None:
    sql_single_quote = "SELECT * FROM {{ ref('my_model') }}"
    assert "my_model" in clean_jinja_for_parsing(sql_single_quote)

    sql_double_quote = 'SELECT * FROM {{ ref("my_model") }}'
    assert "my_model" in clean_jinja_for_parsing(sql_double_quote)

    sql_spaces = "SELECT * FROM {{  ref(  'my_model'  )  }}"
    assert "my_model" in clean_jinja_for_parsing(sql_spaces)


def test_clean_jinja_ref_two_args() -> None:
    sql_single_quote = "SELECT * FROM {{ ref('my_package', 'my_model') }}"
    assert "my_model" in clean_jinja_for_parsing(sql_single_quote)
    assert "my_package" not in clean_jinja_for_parsing(sql_single_quote)

    sql_double_quote = 'SELECT * FROM {{ ref("my_package", "my_model") }}'
    assert "my_model" in clean_jinja_for_parsing(sql_double_quote)
    assert "my_package" not in clean_jinja_for_parsing(sql_double_quote)


def test_clean_jinja_source() -> None:
    sql_single_quote = "SELECT * FROM {{ source('my_source', 'my_table') }}"
    assert "my_table" in clean_jinja_for_parsing(sql_single_quote)
    assert "my_source" not in clean_jinja_for_parsing(sql_single_quote)

    sql_double_quote = 'SELECT * FROM {{ source("my_source", "my_table") }}'
    assert "my_table" in clean_jinja_for_parsing(sql_double_quote)
    assert "my_source" not in clean_jinja_for_parsing(sql_double_quote)


def test_clean_jinja_other_expressions() -> None:
    sql = "SELECT {{ col_name }} FROM table"
    cleaned = clean_jinja_for_parsing(sql)
    assert "__jinja_var__" in cleaned
    assert "col_name" not in cleaned


def test_clean_jinja_statements() -> None:
    sql = "SELECT * FROM table {% if is_incremental() %} WHERE date > '2023-01-01' {% endif %}"
    cleaned = clean_jinja_for_parsing(sql)
    assert "if is_incremental()" not in cleaned
    assert "endif" not in cleaned
    assert "WHERE date" in cleaned


def test_clean_sqlmesh_macros() -> None:
    sql_with_args = "SELECT * FROM table WHERE date > @today()"
    assert "__sqlmesh_macro__" in clean_jinja_for_parsing(sql_with_args)

    sql_no_args = "SELECT * FROM table WHERE date > @today"
    assert "__sqlmesh_macro__" in clean_jinja_for_parsing(sql_no_args)

    sql_nested = "SELECT * FROM table WHERE @my_macro(count(x), 'foo (bar)')"
    cleaned_nested = clean_jinja_for_parsing(sql_nested)
    assert "__sqlmesh_macro__" in cleaned_nested
    assert "count(x)" not in cleaned_nested


def test_clean_sqlmesh_macros_preserves_strings_and_quotes() -> None:
    sql = (
        "SELECT "
        "'user@gmail.com' AS email, "
        "\"col@name\" AS quoted_col, "
        "`backtick@col` AS bt_col, "
        "[bracket@col] AS brk_col, "
        "$$dollar@tag$$ AS d_tag, "
        "$tag$custom@tag$tag$ AS c_tag, "
        "-- line comment with @comment_macro\n"
        "/* block comment with @block_macro */ "
        "regexp_like(col, '.@gmail.com') AS is_gmail, "
        "@today() AS macro_val "
        "FROM table"
    )
    cleaned = clean_jinja_for_parsing(sql)
    assert "'user@gmail.com'" in cleaned
    assert '"col@name"' in cleaned
    assert "`backtick@col`" in cleaned
    assert "[bracket@col]" in cleaned
    assert "$$dollar@tag$$" in cleaned
    assert "$tag$custom@tag$tag$" in cleaned
    assert "-- line comment with @comment_macro" in cleaned
    assert "/* block comment with @block_macro */" in cleaned
    assert "'.@gmail.com'" in cleaned
    assert "__sqlmesh_macro__" in cleaned
    assert "@today()" not in cleaned


def test_clean_jinja_skips_sqlmesh_macros_for_dbt_and_dataform() -> None:
    sql = "SELECT * FROM table WHERE date > @today() AND status = 'active'"
    cleaned_dbt = clean_jinja_for_parsing(sql, provider="dbt")
    assert "__sqlmesh_macro__" not in cleaned_dbt
    assert "@today()" in cleaned_dbt

    cleaned_dataform = clean_jinja_for_parsing(sql, provider="dataform")
    assert "__sqlmesh_macro__" not in cleaned_dataform
    assert "@today()" in cleaned_dataform

    cleaned_sqlmesh = clean_jinja_for_parsing(sql, provider="sqlmesh")
    assert "__sqlmesh_macro__" in cleaned_sqlmesh
    assert "@today()" not in cleaned_sqlmesh


def test_clean_sqlmesh_macros_escapes_and_edge_cases() -> None:
    # 1. Escaped single quotes ('', \')
    sql_single_escapes = r"SELECT 'it''s @not_macro', 'it\'s @not_macro' FROM t"
    cleaned = clean_jinja_for_parsing(sql_single_escapes)
    assert "__sqlmesh_macro__" not in cleaned
    assert r"'it''s @not_macro'" in cleaned
    assert r"'it\'s @not_macro'" in cleaned

    # 2. Escaped double quotes ("", \")
    sql_double_escapes = r'SELECT "col""@not_macro", "col\"@not_macro" FROM t'
    cleaned = clean_jinja_for_parsing(sql_double_escapes)
    assert "__sqlmesh_macro__" not in cleaned
    assert r'"col""@not_macro"' in cleaned
    assert r'"col\"@not_macro"' in cleaned

    # 3. Escaped backticks (``, \`)
    sql_backtick_escapes = "SELECT `bt``@not_macro`, `bt\\`@not_macro` FROM t"
    cleaned = clean_jinja_for_parsing(sql_backtick_escapes)
    assert "__sqlmesh_macro__" not in cleaned
    assert "`bt``@not_macro`" in cleaned
    assert "`bt\\`@not_macro`" in cleaned

    # 4. Identifier-preceded @ (e.g. unquoted user@domain.com)
    sql_email_prefix = "SELECT user@domain FROM t"
    cleaned = clean_jinja_for_parsing(sql_email_prefix)
    assert "__sqlmesh_macro__" not in cleaned
    assert "user@domain" in cleaned

    # 5. Whitespace between macro name and parenthesis
    sql_ws = "SELECT @my_macro   (1, 2) FROM t"
    cleaned = clean_jinja_for_parsing(sql_ws)
    assert "__sqlmesh_macro__" in cleaned
    assert "@my_macro" not in cleaned

    # 6. Escaped quotes within macro call arguments ('', \')
    sql_macro_arg_escapes = r"SELECT @my_macro('it''s (nested)', 'it\'s (nested2)') FROM t"
    cleaned = clean_jinja_for_parsing(sql_macro_arg_escapes)
    assert "__sqlmesh_macro__" in cleaned
    assert "@my_macro" not in cleaned

