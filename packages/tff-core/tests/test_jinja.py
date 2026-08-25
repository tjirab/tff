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
