import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch
from tff.core.model import ModelRepresentation
from tff.core.report import LintFinding
from tff.core.autofix import (
    parse_model_block_args,
    fix_positional_clauses,
    fix_sqlmesh_metadata,
    fix_dbt_metadata,
    fix_dataform_metadata,
    _find_matching_brace,
    _find_matching_paren,
    sync_sqlmesh_model_name,
    sync_dataform_model_name,
    _sync_dbt_schema_yaml_model_name,
    apply_autofixes,
    lift_nested_subqueries,
    expand_select_star,
)


def test_parse_model_block_args():
    block = """
      name sqlmesh_example.violating_model,
      kind FULL,
      owner 'data_team',
      description 'Derived, model',
      grain (id, sub_id)
    """
    args = parse_model_block_args(block)
    assert len(args) == 5
    assert args[0] == ("name", "sqlmesh_example.violating_model")
    assert args[1] == ("kind", "FULL")
    assert args[2] == ("owner", "'data_team'")
    assert args[3] == ("description", "'Derived, model'")
    assert args[4] == ("grain", "(id, sub_id)")


def test_fix_positional_clauses_no_jinja():
    sql = "SELECT a + 1 AS alias, b FROM my_table GROUP BY 1, 2 ORDER BY 1 DESC"
    expected = "SELECT a + 1 AS alias, b FROM my_table GROUP BY alias, b ORDER BY alias DESC"
    fixed = fix_positional_clauses(sql, "ansi")
    assert fixed == expected


def test_fix_positional_clauses_with_jinja():
    sql = "SELECT a + 1 AS alias, {{ ref('other_model') }}.b FROM {{ ref('other_model') }} GROUP BY 1, 2"
    expected = "SELECT a + 1 AS alias, {{ ref('other_model') }}.b FROM {{ ref('other_model') }} GROUP BY alias, {{ ref('other_model') }}.b"
    fixed = fix_positional_clauses(sql, "ansi")
    assert fixed == expected


def test_fix_positional_clauses_sqlmesh():
    sql = "MODEL (\n  name my_model\n);\nSELECT a FROM table GROUP BY 1"
    expected = "MODEL (\n  name my_model\n);\n\nSELECT a FROM table GROUP BY a"
    fixed = fix_positional_clauses(sql, "ansi")
    assert fixed == expected


def test_fix_positional_clauses_invalid_sql():
    sql = "SELECT FROM WHERE GROUP BY 1"
    fixed = fix_positional_clauses(sql, "ansi")
    assert fixed == sql


def test_fix_sqlmesh_metadata(tmp_path: Path):
    model_file = tmp_path / "model.sql"
    
    # 1. Missing both owner and description
    model_file.write_text("MODEL (\n  name my_model\n);\nSELECT 1;", encoding="utf-8")
    log = fix_sqlmesh_metadata(model_file, missing_owner=True, missing_description=True)
    assert log == "Added missing metadata to MODEL block in model.sql"
    content = model_file.read_text(encoding="utf-8")
    assert "owner 'TODO: Add owner'" in content
    assert "description 'TODO: Add description'" in content

    # 2. Only missing owner
    model_file.write_text("MODEL (\n  name my_model,\n  description 'already there'\n);\nSELECT 1;", encoding="utf-8")
    log = fix_sqlmesh_metadata(model_file, missing_owner=True, missing_description=True)
    assert log == "Added missing metadata to MODEL block in model.sql"
    content = model_file.read_text(encoding="utf-8")
    assert "owner 'TODO: Add owner'" in content
    assert "description 'already there'" in content

    # 3. None missing
    model_file.write_text("MODEL (\n  name my_model,\n  owner 'someone',\n  description 'desc'\n);\nSELECT 1;", encoding="utf-8")
    log = fix_sqlmesh_metadata(model_file, missing_owner=True, missing_description=True)
    assert log is None


def test_fix_dbt_metadata_existing_file(tmp_path: Path):
    model_file = tmp_path / "my_model.sql"
    model_file.touch()
    
    schema_file = tmp_path / "schema.yml"
    schema_file.write_text(yaml.safe_dump({
        "version": 2,
        "models": [
            {"name": "other_model"},
            {"name": "my_model", "description": "existing desc"}
        ]
    }), encoding="utf-8")

    # missing owner
    log = fix_dbt_metadata(model_file, "my_model", missing_owner=True, missing_description=True)
    assert log == "Updated metadata for model my_model in schema.yml"
    
    with open(schema_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["models"][1]["description"] == "existing desc"  # Not overwritten
    assert data["models"][1]["meta"]["owner"] == "TODO: Add owner"


def test_fix_dbt_metadata_appended(tmp_path: Path):
    model_file = tmp_path / "my_model.sql"
    model_file.touch()
    
    schema_file = tmp_path / "schema.yml"
    schema_file.write_text(yaml.safe_dump({
        "version": 2,
        "models": [{"name": "other_model"}]
    }), encoding="utf-8")

    log = fix_dbt_metadata(model_file, "my_model", missing_owner=True, missing_description=True)
    assert log == "Appended metadata for model my_model to schema.yml"
    
    with open(schema_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert len(data["models"]) == 2
    assert data["models"][1]["name"] == "my_model"
    assert data["models"][1]["description"] == "TODO: Add description"
    assert data["models"][1]["meta"]["owner"] == "TODO: Add owner"


def test_fix_dbt_metadata_scaffold(tmp_path: Path):
    model_file = tmp_path / "my_model.sql"
    model_file.touch()

    log = fix_dbt_metadata(model_file, "my_model", missing_owner=True, missing_description=True)
    assert log == "Scaffolded schema.yml for model my_model"
    
    schema_file = tmp_path / "schema.yml"
    assert schema_file.exists()
    with open(schema_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["version"] == 2
    assert data["models"][0]["name"] == "my_model"
    assert data["models"][0]["description"] == "TODO: Add description"
    assert data["models"][0]["meta"]["owner"] == "TODO: Add owner"


def test_fix_dbt_metadata_preserves_comments(tmp_path: Path):
    model_file = tmp_path / "my_model.sql"
    model_file.touch()

    schema_file = tmp_path / "schema.yml"
    original_yaml = (
        "# Top-level comment\n"
        "version: 2\n"
        "\n"
        "models:\n"
        "  # Other model comment\n"
        "  - name: other_model\n"
        '    description: "other desc" # inline comment\n'
        "\n"
        "  # My model comment\n"
        "  - name: my_model\n"
        '    description: "existing desc"\n'
    )
    schema_file.write_text(original_yaml, encoding="utf-8")

    log = fix_dbt_metadata(model_file, "my_model", missing_owner=True, missing_description=False)
    assert log == "Updated metadata for model my_model in schema.yml"

    content = schema_file.read_text(encoding="utf-8")
    assert "# Top-level comment" in content
    assert "# Other model comment" in content
    assert "# inline comment" in content
    assert "# My model comment" in content
    assert "owner:" in content
    assert "TODO: Add owner" in content


def test_apply_autofixes(tmp_path: Path):
    # Setup files
    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT a FROM t GROUP BY 1", encoding="utf-8")

    findings = [
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="error",
            model="my_model",
            path="models/marts/my_model.sql",
            message="Use column name instead."
        ),
        LintFinding(
            check="nomissingowner",
            severity="error",
            model="my_model",
            path="models/marts/my_model.sql",
            message="Owner missing."
        )
    ]

    models = {
        "my_model": ModelRepresentation(
            name="my_model",
            path=str(sql_file),
            dialect="ansi"
        )
    }

    logs = apply_autofixes(tmp_path, "dbt", findings, models)
    assert "Fixed positional GROUP BY/ORDER BY in my_model.sql" in logs
    assert "Scaffolded schema.yml for model my_model" in logs

    # Verify SQL file modified
    assert sql_file.read_text(encoding="utf-8") == "SELECT a FROM t GROUP BY a"

    # Verify schema.yml created
    schema_file = tmp_path / "models/marts/schema.yml"
    assert schema_file.exists()
    with open(schema_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert data["models"][0]["meta"]["owner"] == "TODO: Add owner"

    # Test with SQLMesh provider to cover line 321-323
    sql_file_mesh = tmp_path / "models/marts/my_model_mesh.sql"
    sql_file_mesh.write_text("MODEL (\n  name my_model_mesh\n);\nSELECT a FROM t GROUP BY 1", encoding="utf-8")
    
    findings_mesh = [
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="error",
            model="my_model_mesh",
            path="models/marts/my_model_mesh.sql",
            message="Use column name instead."
        ),
        LintFinding(
            check="nomissingowner",
            severity="error",
            model="my_model_mesh",
            path="models/marts/my_model_mesh.sql",
            message="Owner missing."
        )
    ]
    
    models_mesh = {
        "my_model_mesh": ModelRepresentation(
            name="my_model_mesh",
            path=str(sql_file_mesh),
            dialect="ansi"
        )
    }
    
    logs_mesh = apply_autofixes(tmp_path, "sqlmesh", findings_mesh, models_mesh)
    assert "Fixed positional GROUP BY/ORDER BY in my_model_mesh.sql" in logs_mesh
    assert "Added missing metadata to MODEL block in my_model_mesh.sql" in logs_mesh
    
    mesh_content = sql_file_mesh.read_text(encoding="utf-8")
    assert "owner 'TODO: Add owner'" in mesh_content
    assert "GROUP BY a" in mesh_content


def test_parse_model_block_args_edge_cases():
    block = ", , name my_model, no_value_key, kind VIEW"
    args = parse_model_block_args(block)
    # empty strings should be skipped, no_value_key should be mapped to ""
    assert len(args) == 3
    assert args[0] == ("name", "my_model")
    assert args[1] == ("no_value_key", "")
    assert args[2] == ("kind", "VIEW")


def test_fix_positional_clauses_valid_dialect():
    # Covers line 68 (successful dialect resolution)
    sql = "SELECT a FROM t GROUP BY 1"
    fixed = fix_positional_clauses(sql, "postgres")
    assert fixed == "SELECT a FROM t GROUP BY a"


def test_fix_positional_clauses_out_of_bounds():
    # Covers line 126 (pos reference out of bounds)
    sql = "SELECT a FROM t GROUP BY 99"
    fixed = fix_positional_clauses(sql, "postgres")
    assert fixed == sql


def test_fix_positional_clauses_non_literal_and_unaliased_order():
    # Covers lines 128 (non-literal in GROUP BY) and 142 (unaliased in ORDER BY)
    sql = "SELECT a FROM t GROUP BY a, 1 ORDER BY 1"
    fixed = fix_positional_clauses(sql, "postgres")
    assert fixed == "SELECT a FROM t GROUP BY a, a ORDER BY a"


def test_fix_positional_clauses_no_changes():
    # Covers line 145 (not modified check returning early)
    sql = "SELECT a FROM t GROUP BY a"
    fixed = fix_positional_clauses(sql, "postgres")
    assert fixed == sql


def test_fix_sqlmesh_metadata_exceptions(tmp_path: Path):
    # 1. Trigger read exception by passing a directory path
    dir_path = tmp_path / "sub_dir"
    dir_path.mkdir()
    log = fix_sqlmesh_metadata(dir_path, True, True)
    assert log is None

    # 2. Trigger no MODEL block found
    sql_file = tmp_path / "no_model.sql"
    sql_file.write_text("SELECT 1;", encoding="utf-8")
    log = fix_sqlmesh_metadata(sql_file, True, True)
    assert log is None

    # 3. Trigger write exception by mocking write_text (using write permission failure)
    sql_file_fail = tmp_path / "fail.sql"
    sql_file_fail.write_text("MODEL (\n  name my_model\n);\nSELECT 1;", encoding="utf-8")
    # Change permissions to read-only to cause write failure
    sql_file_fail.chmod(0o444)
    try:
        log = fix_sqlmesh_metadata(sql_file_fail, True, True)
        assert log is not None
        assert "Failed to write" in log
    finally:
        sql_file_fail.chmod(0o644)  # restore


def test_fix_dbt_metadata_exceptions_and_formats(tmp_path: Path):
    model_file = tmp_path / "my_model.sql"
    model_file.touch()

    # 1. YAML file load exception (broken yaml)
    schema_file = tmp_path / "schema.yml"
    schema_file.write_text("invalid: - [ : yaml", encoding="utf-8")
    # should be skipped, falls back to new schema.yml creation
    log = fix_dbt_metadata(model_file, "my_model", True, True)
    assert "schema.yml" in log

    # 2. YAML file loaded is list or lacks models list
    schema_file.write_text(yaml.safe_dump([1, 2, 3]), encoding="utf-8")
    log = fix_dbt_metadata(model_file, "my_model", True, True)
    assert "schema.yml" in log

    # 3. Existing yml where model already has description/owner (modified remains False)
    schema_file.write_text(yaml.safe_dump({
        "version": 2,
        "models": [{"name": "my_model", "description": "desc", "meta": {"owner": "owner"}}]
    }), encoding="utf-8")
    log = fix_dbt_metadata(model_file, "my_model", True, True)
    assert log is None

    # 4. Trigger write exception on existing file (read-only file)
    schema_file.write_text(yaml.safe_dump({
        "version": 2,
        "models": [{"name": "my_model"}]
    }), encoding="utf-8")
    schema_file.chmod(0o444)
    try:
        log = fix_dbt_metadata(model_file, "my_model", True, True)
        assert log is not None
        assert "Failed to write dbt metadata" in log
    finally:
        schema_file.chmod(0o644)


def test_fix_dbt_metadata_schema_yml_corrupted(tmp_path: Path):
    model_file = tmp_path / "my_model.sql"
    model_file.touch()

    schema_file = tmp_path / "schema.yml"
    
    # 1. schema_path exists but is invalid yaml (raises exception)
    schema_file.write_text("invalid: [yaml", encoding="utf-8")
    log = fix_dbt_metadata(model_file, "my_model", True, True)
    assert "schema.yml" in log

    # 2. schema_path data loaded is list (not dict)
    schema_file.write_text(yaml.safe_dump([1, 2, 3]), encoding="utf-8")
    log = fix_dbt_metadata(model_file, "my_model", True, True)
    assert "schema.yml" in log

    # 3. Trigger write/scaffold schema.yml exception (using permission check)
    # We can create a read-only directory named schema.yml so write fails
    schema_file.unlink()
    schema_file.mkdir()  # make it a directory to trigger IsADirectoryError / PermissionError on open
    try:
        log = fix_dbt_metadata(model_file, "my_model", True, True)
        assert log is not None
        assert "Failed to write/scaffold schema.yml" in log
    finally:
        schema_file.rmdir()


def test_apply_autofixes_untracked_paths_and_exceptions(tmp_path: Path):
    # 1. Non-existent path in LintFinding should be skipped
    findings = [
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="error",
            model="my_model",
            path="non_existent.sql",
            message="errors"
        )
    ]
    logs = apply_autofixes(tmp_path, "dbt", findings, {})
    assert len(logs) == 0

    # 2. Trigger read/write exception in apply_autofixes
    # We create a directory instead of a file for my_model.sql
    dir_path = tmp_path / "my_model.sql"
    dir_path.mkdir(parents=True, exist_ok=True)
    findings = [
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="error",
            model="my_model",
            path="my_model.sql",
            message="errors"
        )
    ]
    models = {
        "my_model": ModelRepresentation(
            name="my_model",
            path=str(dir_path),
            dialect="postgres"
        )
    }
    logs = apply_autofixes(tmp_path, "dbt", findings, models)
    assert len(logs) == 1
    assert "Failed to fix positional references" in logs[0]


def test_fix_positional_clauses_dataform_edge_cases():
    # 1. Escaped quote inside string in config block (line 87)
    sql_with_escaped_quote = """config {
  type: "table",
  description: "Test \\"escaped quote\\" here"
}
SELECT a FROM t GROUP BY 1"""
    fixed = fix_positional_clauses(sql_with_escaped_quote, "bigquery")
    assert "GROUP BY a" in fixed
    assert 'description: "Test \\"escaped quote\\" here"' in fixed

    # 2. Unclosed brace in config block (lines 103-104)
    sql_unclosed = """config {
  type: "table"
SELECT a FROM t GROUP BY 1"""
    fixed_unclosed = fix_positional_clauses(sql_unclosed, "bigquery")
    assert fixed_unclosed == sql_unclosed


def test_find_matching_brace_edge_cases():
    assert _find_matching_brace("", 0) == -1
    assert _find_matching_brace("abc", -1) == -1
    assert _find_matching_brace("abc", 5) == -1
    assert _find_matching_brace("abc", 0) == -1

    # Unclosed brace
    assert _find_matching_brace("{ abc", 0) == -1

    # Line comment until EOF (no newline)
    assert _find_matching_brace("{ // no newline at all", 0) == -1

    # Block comment until EOF (no */)
    assert _find_matching_brace("{ /* unclosed block comment", 0) == -1

    # Escaped quote inside string
    code = '{"hello \\" world"}'
    assert _find_matching_brace(code, 0) == len(code) - 1

    # Block comment with braces
    code2 = '{ /* { inside } */ }'
    assert _find_matching_brace(code2, 0) == len(code2) - 1

    # Line comment with braces
    code3 = "{\n // { line comment\n}"
    assert _find_matching_brace(code3, 0) == len(code3) - 1


def test_fix_dataform_metadata_no_missing_or_invalid_path(tmp_path: Path):
    # None missing
    sqlx_file = tmp_path / "test.sqlx"
    sqlx_file.write_text("SELECT 1", encoding="utf-8")
    assert fix_dataform_metadata(sqlx_file, False, False) is None

    # Invalid extension (.txt)
    txt_file = tmp_path / "test.txt"
    txt_file.write_text("SELECT 1", encoding="utf-8")
    assert fix_dataform_metadata(txt_file, True, True) is None

    # Directory
    sub_dir = tmp_path / "subdir"
    sub_dir.mkdir()
    assert fix_dataform_metadata(sub_dir, True, True) is None

    # Non-existent
    assert fix_dataform_metadata(tmp_path / "does_not_exist.sqlx", True, True) is None

    # Read error
    with patch.object(Path, "read_text", side_effect=OSError("Read error")):
        assert fix_dataform_metadata(sqlx_file, True, True) is None


def test_fix_dataform_metadata_scaffold(tmp_path: Path):
    # 1. Missing both on file with SQL
    f1 = tmp_path / "model1.sqlx"
    f1.write_text("SELECT 1 AS id\n", encoding="utf-8")
    log1 = fix_dataform_metadata(f1, missing_owner=True, missing_description=True)
    assert log1 == "Scaffolded config block in model1.sqlx"
    content1 = f1.read_text(encoding="utf-8")
    assert 'description: "TODO: Add description"' in content1
    assert 'owner: "TODO: Add owner"' in content1
    assert 'type: "view"' in content1
    assert "SELECT 1 AS id" in content1

    # 2. Missing only description
    f2 = tmp_path / "model2.sqlx"
    f2.write_text("SELECT 2 AS id", encoding="utf-8")
    log2 = fix_dataform_metadata(f2, missing_owner=False, missing_description=True)
    assert log2 == "Scaffolded config block in model2.sqlx"
    content2 = f2.read_text(encoding="utf-8")
    assert 'description: "TODO: Add description"' in content2
    assert "bigquery:" not in content2

    # 3. Missing only owner
    f3 = tmp_path / "model3.sqlx"
    f3.write_text("SELECT 3 AS id", encoding="utf-8")
    log3 = fix_dataform_metadata(f3, missing_owner=True, missing_description=False)
    assert log3 == "Scaffolded config block in model3.sqlx"
    content3 = f3.read_text(encoding="utf-8")
    assert 'owner: "TODO: Add owner"' in content3
    assert "description:" not in content3

    # 4. Empty file scaffolding
    f4 = tmp_path / "model4.sqlx"
    f4.write_text("", encoding="utf-8")
    log4 = fix_dataform_metadata(f4, missing_owner=True, missing_description=True)
    assert log4 == "Scaffolded config block in model4.sqlx"
    content4 = f4.read_text(encoding="utf-8")
    assert content4.endswith("}\n")

    # 5. Write failure during scaffolding
    f5 = tmp_path / "model5.sqlx"
    f5.write_text("SELECT 5", encoding="utf-8")
    f5.chmod(0o444)
    try:
        log5 = fix_dataform_metadata(f5, True, True)
        assert log5 is not None
        assert "Failed to write Dataform metadata" in log5
    finally:
        f5.chmod(0o644)


def test_fix_dataform_metadata_existing_config(tmp_path: Path):
    # 1. Missing both in standard config
    f1 = tmp_path / "stg_orders.sqlx"
    f1.write_text("""config {
  type: "table",
  // Table comment
  tags: ["daily"]
}

SELECT 1 AS id""", encoding="utf-8")

    log1 = fix_dataform_metadata(f1, missing_owner=True, missing_description=True)
    assert log1 == "Added missing metadata to config block in stg_orders.sqlx"
    c1 = f1.read_text(encoding="utf-8")
    assert 'description: "TODO: Add description"' in c1
    assert 'owner: "TODO: Add owner"' in c1
    assert '// Table comment' in c1
    assert 'tags: ["daily"]' in c1

    # 2. Existing bigquery block without labels
    f2 = tmp_path / "stg_bq.sqlx"
    f2.write_text("""config {
  type: "table",
  bigquery: {
    partitionBy: "DATE(created_at)"
  }
}
SELECT 1""", encoding="utf-8")
    log2 = fix_dataform_metadata(f2, missing_owner=True, missing_description=False)
    assert log2 == "Added missing metadata to config block in stg_bq.sqlx"
    c2 = f2.read_text(encoding="utf-8")
    assert 'owner: "TODO: Add owner"' in c2
    assert 'partitionBy: "DATE(created_at)"' in c2

    # 3. Existing bigquery block with labels (multi-line)
    f3 = tmp_path / "stg_labels.sqlx"
    f3.write_text("""config {
  type: "table",
  bigquery: {
    labels: {
      env: "prod"
    }
  }
}
SELECT 1""", encoding="utf-8")
    log3 = fix_dataform_metadata(f3, missing_owner=True, missing_description=False)
    assert log3 == "Added missing metadata to config block in stg_labels.sqlx"
    c3 = f3.read_text(encoding="utf-8")
    assert 'owner: "TODO: Add owner"' in c3
    assert 'env: "prod"' in c3

    # 4. Existing bigquery block with labels (single-line)
    f4 = tmp_path / "stg_labels_single.sqlx"
    f4.write_text("""config {
  type: "table",
  bigquery: { labels: { env: "prod" } }
}
SELECT 1""", encoding="utf-8")
    log4 = fix_dataform_metadata(f4, missing_owner=True, missing_description=False)
    assert log4 == "Added missing metadata to config block in stg_labels_single.sqlx"
    c4 = f4.read_text(encoding="utf-8")
    assert 'owner: "TODO: Add owner"' in c4
    assert 'env: "prod"' in c4

    # 5. Existing bigquery block (single-line without labels)
    f5 = tmp_path / "stg_bq_single.sqlx"
    f5.write_text("""config {
  type: "table",
  bigquery: { partitionBy: "dt" }
}
SELECT 1""", encoding="utf-8")
    log5 = fix_dataform_metadata(f5, missing_owner=True, missing_description=False)
    assert log5 == "Added missing metadata to config block in stg_bq_single.sqlx"
    c5 = f5.read_text(encoding="utf-8")
    assert 'owner: "TODO: Add owner"' in c5
    assert 'partitionBy: "dt"' in c5

    # 6. Existing empty description and owner strings
    f6 = tmp_path / "empty_strings.sqlx"
    f6.write_text("""config {
  description: "",
  owner: ''
}
SELECT 1""", encoding="utf-8")
    log6 = fix_dataform_metadata(f6, missing_owner=True, missing_description=True)
    assert log6 == "Added missing metadata to config block in empty_strings.sqlx"
    c6 = f6.read_text(encoding="utf-8")
    assert 'description: "TODO: Add description"' in c6
    assert 'owner: "TODO: Add owner"' in c6

    # 7. Unclosed brace in existing config block
    f7 = tmp_path / "unclosed.sqlx"
    f7.write_text("config { type: 'view'\nSELECT 1", encoding="utf-8")
    assert fix_dataform_metadata(f7, True, True) is None

    # 8. Single-line config block: config { type: "view" }
    f8 = tmp_path / "single_line.sqlx"
    f8.write_text("config { type: 'view' }\nSELECT 1", encoding="utf-8")
    log8 = fix_dataform_metadata(f8, True, True)
    assert log8 == "Added missing metadata to config block in single_line.sqlx"
    c8 = f8.read_text(encoding="utf-8")
    assert 'description: "TODO: Add description"' in c8
    assert 'owner: "TODO: Add owner"' in c8

    # 9. Empty config block: config {}
    f9 = tmp_path / "empty_config.sqlx"
    f9.write_text("config {}\nSELECT 1", encoding="utf-8")
    log9 = fix_dataform_metadata(f9, True, True)
    assert log9 == "Added missing metadata to config block in empty_config.sqlx"
    c9 = f9.read_text(encoding="utf-8")
    assert 'description: "TODO: Add description"' in c9
    assert 'owner: "TODO: Add owner"' in c9

    # 10. Already has owner and description
    f10 = tmp_path / "complete.sqlx"
    f10.write_text("""config {
  description: "Complete model",
  bigquery: {
    labels: {
      owner: "data_team"
    }
  }
}
SELECT 1""", encoding="utf-8")
    assert fix_dataform_metadata(f10, True, True) is None

    # 11. Write failure on existing config
    f11 = tmp_path / "fail_write.sqlx"
    f11.write_text("config { type: 'view' }\nSELECT 1", encoding="utf-8")
    f11.chmod(0o444)
    try:
        log11 = fix_dataform_metadata(f11, True, True)
        assert log11 is not None
        assert "Failed to write Dataform metadata" in log11
    finally:
        f11.chmod(0o644)

    # 12. Write failure on existing config with empty strings
    f12 = tmp_path / "fail_write_empty_strings.sqlx"
    f12.write_text("config { description: '' }\nSELECT 1", encoding="utf-8")
    f12.chmod(0o444)
    try:
        log12 = fix_dataform_metadata(f12, missing_owner=False, missing_description=True)
        assert log12 is not None
        assert "Failed to write Dataform metadata" in log12
    finally:
        f12.chmod(0o644)


def test_apply_autofixes_dataform(tmp_path: Path):
    sqlx_file = tmp_path / "definitions/marts/orders.sqlx"
    sqlx_file.parent.mkdir(parents=True, exist_ok=True)
    sqlx_file.write_text("""config {
  type: "view"
}
SELECT id, count(*) AS cnt FROM orders GROUP BY 1
""", encoding="utf-8")

    findings = [
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="error",
            model="orders",
            path="definitions/marts/orders.sqlx",
            message="Use column name instead."
        ),
        LintFinding(
            check="nomissingowner",
            severity="error",
            model="orders",
            path="definitions/marts/orders.sqlx",
            message="Owner missing."
        ),
        LintFinding(
            check="nomissingdescription",
            severity="error",
            model="orders",
            path="definitions/marts/orders.sqlx",
            message="Description missing."
        )
    ]

    models = {
        "orders": ModelRepresentation(
            name="orders",
            path=str(sqlx_file),
            dialect="bigquery"
        )
    }

    logs = apply_autofixes(tmp_path, "dataform", findings, models)
    assert any("Fixed positional GROUP BY/ORDER BY" in item for item in logs)
    assert any("Added missing metadata to config block" in item for item in logs)

    content = sqlx_file.read_text(encoding="utf-8")
    assert 'description: "TODO: Add description"' in content
    assert 'owner: "TODO: Add owner"' in content
    assert "GROUP BY id" in content


def test_lift_nested_subqueries_from_clause():
    # 1. With alias
    sql1 = "SELECT * FROM (SELECT 1 AS a) sub"
    expected1 = "WITH sub AS (SELECT 1 AS a) SELECT * FROM sub"
    assert lift_nested_subqueries(sql1, "ansi") == expected1

    # 2. Without alias
    sql2 = "SELECT * FROM (SELECT 1 AS a)"
    expected2 = "WITH __extracted_cte_1 AS (SELECT 1 AS a) SELECT * FROM __extracted_cte_1"
    assert lift_nested_subqueries(sql2, "ansi") == expected2

    # 3. With table alias containing column list
    sql3 = "SELECT * FROM (SELECT 1, 2) sub(a, b)"
    expected3 = "WITH sub(a, b) AS (SELECT 1, 2) SELECT * FROM sub"
    assert lift_nested_subqueries(sql3, "ansi") == expected3


def test_lift_nested_subqueries_joins():
    # 1. LEFT JOIN
    sql_left = "SELECT * FROM t LEFT JOIN (SELECT 2 AS b) sub ON t.id = sub.b"
    assert lift_nested_subqueries(sql_left, "ansi") == "WITH sub AS (SELECT 2 AS b) SELECT * FROM t LEFT JOIN sub ON t.id = sub.b"

    # 2. RIGHT JOIN
    sql_right = "SELECT * FROM t RIGHT JOIN (SELECT 2 AS b) sub ON t.id = sub.b"
    assert lift_nested_subqueries(sql_right, "ansi") == "WITH sub AS (SELECT 2 AS b) SELECT * FROM t RIGHT JOIN sub ON t.id = sub.b"

    # 3. FULL JOIN
    sql_full = "SELECT * FROM t FULL JOIN (SELECT 2 AS b) sub ON t.id = sub.b"
    assert lift_nested_subqueries(sql_full, "ansi") == "WITH sub AS (SELECT 2 AS b) SELECT * FROM t FULL JOIN sub ON t.id = sub.b"

    # 4. CROSS JOIN
    sql_cross = "SELECT * FROM t CROSS JOIN (SELECT 2 AS b) sub"
    assert lift_nested_subqueries(sql_cross, "ansi") == "WITH sub AS (SELECT 2 AS b) SELECT * FROM t CROSS JOIN sub"

    # 5. INNER JOIN with USING
    sql_using = "SELECT * FROM t JOIN (SELECT 2 AS id) sub USING (id)"
    assert lift_nested_subqueries(sql_using, "ansi") == "WITH sub AS (SELECT 2 AS id) SELECT * FROM t JOIN sub USING (id)"


def test_lift_nested_subqueries_multiple_subqueries():
    sql = "SELECT * FROM (SELECT 1 AS a) sub1 LEFT JOIN (SELECT 2 AS b) sub2 ON sub1.a = sub2.b"
    expected = "WITH sub1 AS (SELECT 1 AS a), sub2 AS (SELECT 2 AS b) SELECT * FROM sub1 LEFT JOIN sub2 ON sub1.a = sub2.b"
    assert lift_nested_subqueries(sql, "ansi") == expected


def test_lift_nested_subqueries_existing_ctes_and_collision():
    # 1. Preserves existing CTEs and appends
    sql1 = "WITH existing AS (SELECT 0) SELECT * FROM (SELECT 1 AS a) sub"
    expected1 = "WITH existing AS (SELECT 0), sub AS (SELECT 1 AS a) SELECT * FROM sub"
    assert lift_nested_subqueries(sql1, "ansi") == expected1

    # 2. Disambiguates CTE alias when name collides with existing CTE
    sql2 = "WITH sub AS (SELECT 0) SELECT * FROM (SELECT 1 AS a) sub"
    expected2 = "WITH sub AS (SELECT 0), sub_1 AS (SELECT 1 AS a) SELECT * FROM sub_1 AS sub"
    assert lift_nested_subqueries(sql2, "ansi") == expected2

    # 3. Disambiguates when __extracted_cte_1 is already an existing CTE name
    sql3 = "WITH __extracted_cte_1 AS (SELECT 0) SELECT * FROM (SELECT 1 AS a)"
    expected3 = "WITH __extracted_cte_1 AS (SELECT 0), __extracted_cte_2 AS (SELECT 1 AS a) SELECT * FROM __extracted_cte_2"
    assert lift_nested_subqueries(sql3, "ansi") == expected3

    # 4. Disambiguates when both sub and sub_1 already exist
    sql4 = "WITH sub AS (SELECT 0), sub_1 AS (SELECT 0) SELECT * FROM (SELECT 1 AS a) sub"
    expected4 = "WITH sub AS (SELECT 0), sub_1 AS (SELECT 0), sub_2 AS (SELECT 1 AS a) SELECT * FROM sub_2 AS sub"
    assert lift_nested_subqueries(sql4, "ansi") == expected4


def test_lift_nested_subqueries_templating_and_blocks():
    # 1. Jinja templating preserved
    sql_jinja = "SELECT * FROM (SELECT {{ ref('other_model') }}.col FROM {{ ref('other_model') }}) sub"
    expected_jinja = "WITH sub AS (SELECT {{ ref('other_model') }}.col FROM {{ ref('other_model') }}) SELECT * FROM sub"
    assert lift_nested_subqueries(sql_jinja, "ansi") == expected_jinja

    # 2. SQLMesh macro and MODEL block preserved
    sql_mesh = "MODEL (\n  name my_model\n);\n\nSELECT * FROM (SELECT @my_macro(val) AS x FROM my_table) sub"
    expected_mesh = "MODEL (\n  name my_model\n);\n\nWITH sub AS (SELECT @my_macro(val) AS x FROM my_table) SELECT * FROM sub"
    assert lift_nested_subqueries(sql_mesh, "duckdb") == expected_mesh

    # 3. Dataform ${ref(...)} and config block preserved
    sql_df = 'config {\n  type: "table"\n}\n\nSELECT * FROM (SELECT ${ref("other_model")}.col FROM ${ref("other_model")}) sub'
    expected_df = 'config {\n  type: "table"\n}\n\nWITH sub AS (SELECT ${ref("other_model")}.col FROM ${ref("other_model")}) SELECT * FROM sub'
    assert lift_nested_subqueries(sql_df, "bigquery") == expected_df


def test_lift_nested_subqueries_edge_cases():
    # 1. No subqueries
    sql_plain = "SELECT a, b FROM my_table"
    assert lift_nested_subqueries(sql_plain, "ansi") == sql_plain

    # 2. Invalid SQL parsing exception
    sql_invalid = "SELECT FROM WHERE"
    assert lift_nested_subqueries(sql_invalid, "ansi") == sql_invalid

    # 3. Non-SELECT statement
    sql_create = "CREATE TABLE foo AS SELECT 1"
    assert lift_nested_subqueries(sql_create, "duckdb") == sql_create


def test_apply_autofixes_lift_nested_subqueries(tmp_path: Path):
    sql_file = tmp_path / "models/complex_subquery.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM (SELECT 1 AS a) sub", encoding="utf-8")

    findings = [
        LintFinding(
            check="sqlcomplexity",
            severity="warning",
            model="complex_subquery",
            path="models/complex_subquery.sql",
            message="complex_subquery: WARN: nested subquery in final SELECT — prefer CTEs per style guide",
        )
    ]

    models = {
        "complex_subquery": ModelRepresentation(
            name="complex_subquery",
            path=str(sql_file),
            dialect="ansi",
        )
    }

    logs = apply_autofixes(tmp_path, "dbt", findings, models)
    assert any("Refactored nested subqueries in final SELECT to CTEs" in log for log in logs)
    assert sql_file.read_text(encoding="utf-8") == "WITH sub AS (SELECT 1 AS a) SELECT * FROM sub"

    # Running again when file is already clean produces no changes and no log
    logs_noop = apply_autofixes(tmp_path, "dbt", findings, models)
    assert not any("Refactored nested subqueries" in log for log in logs_noop)

    # Exception during write logs failure
    sql_file.chmod(0o444)
    # Put unrefactored content using write_bytes with chmod override
    try:
        sql_file.chmod(0o644)
        sql_file.write_text("SELECT * FROM (SELECT 1 AS a) sub", encoding="utf-8")
        sql_file.chmod(0o444)
        logs_fail = apply_autofixes(tmp_path, "dbt", findings, models)
        assert any("Failed to refactor nested subqueries" in log for log in logs_fail)
    finally:
        sql_file.chmod(0o644)


def test_apply_autofixes_multiple_project_roots(tmp_path: Path):
    r1 = tmp_path / "repo1"
    r2 = tmp_path / "repo2"
    r1.mkdir()
    r2.mkdir()

    m1_file = r1 / "models" / "m1.sql"
    m1_file.parent.mkdir(parents=True, exist_ok=True)
    m1_file.write_text("SELECT a, b FROM table GROUP BY 1, 2", encoding="utf-8")

    m2_file = r2 / "models" / "m2.sql"
    m2_file.parent.mkdir(parents=True, exist_ok=True)
    m2_file.write_text("MODEL (name m2); SELECT 1 AS x", encoding="utf-8")

    findings = [
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="error",
            model="m1",
            path=str(m1_file.resolve()),
            message="Avoid positional group by",
        ),
        LintFinding(
            check="nomissingowner",
            severity="error",
            model="m2",
            path="models/m2.sql",
            message="Model is missing owner",
        ),
    ]

    models = {
        "m1": ModelRepresentation(name="m1", path=str(m1_file), dialect="ansi"),
        "m2": ModelRepresentation(name="m2", path=str(m2_file), dialect="ansi"),
    }

    mock_adapter = MagicMock()
    mock_adapter.apply_metadata_fix.return_value = "Fixed metadata in m2.sql"

    logs = apply_autofixes([r1, r2], mock_adapter, findings, models)
    assert any("Fixed positional GROUP BY/ORDER BY in m1.sql" in log for log in logs)
    assert "Fixed metadata in m2.sql" in logs

    # Check that m1 was written
    assert "GROUP BY a, b" in m1_file.read_text(encoding="utf-8")

    # Check that apply_metadata_fix was called with matching_root=r2
    mock_adapter.apply_metadata_fix.assert_called_once_with(
        project_root=r2.resolve(),
        abs_path=m2_file.resolve(),
        model_name="m2",
        missing_owner=True,
        missing_description=False,
    )


def test_expand_select_star_single_table_sqlmesh():
    m_upstream = ModelRepresentation(
        name="sqlmesh_example.upstream_model",
        path="models/upstream.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT", "customer_name": "TEXT", "created_at": "TIMESTAMP"},
    )
    models = {"sqlmesh_example.upstream_model": m_upstream}

    sql = "MODEL (\n  name sqlmesh_example.my_model\n);\n\nSELECT * FROM sqlmesh_example.upstream_model"
    fixed_sql, warnings = expand_select_star(sql, "duckdb", models, "my_model")
    assert not warnings
    assert fixed_sql == (
        "MODEL (\n  name sqlmesh_example.my_model\n);\n\n"
        "SELECT id, customer_name, created_at FROM sqlmesh_example.upstream_model"
    )


def test_expand_select_star_single_table_dbt_and_dataform():
    m_orders = ModelRepresentation(
        name="orders",
        path="models/orders.sql",
        dialect="duckdb",
        columns_to_types={"order_id": "INT", "amount": "NUMERIC"},
    )
    models = {"orders": m_orders}

    # dbt with jinja ref
    sql_dbt = "SELECT * FROM {{ ref('orders') }}"
    fixed_dbt, warnings_dbt = expand_select_star(sql_dbt, "duckdb", models, "stg_orders")
    assert not warnings_dbt
    assert fixed_dbt == "SELECT order_id, amount FROM {{ ref('orders') }}"

    # Dataform config block and ${ref(...)}
    sql_df = "config {\n  type: \"table\"\n}\n\nSELECT * FROM ${ref(\"orders\")}"
    fixed_df, warnings_df = expand_select_star(sql_df, "bigquery", models, "stg_orders")
    assert not warnings_df
    assert fixed_df == "config {\n  type: \"table\"\n}\n\nSELECT order_id, amount FROM ${ref(\"orders\")}"


def test_expand_select_star_cte_expansion():
    # CTE with explicit projections
    sql_cte = "WITH some_cte AS (SELECT 1 AS id, 'alice' AS name) SELECT * FROM some_cte"
    fixed_cte, warnings_cte = expand_select_star(sql_cte, "ansi")
    assert not warnings_cte
    assert fixed_cte == "WITH some_cte AS (SELECT 1 AS id, 'alice' AS name) SELECT id, name FROM some_cte"

    # CTE with alias column names
    sql_alias_cols = "WITH some_cte(col_a, col_b) AS (SELECT 1, 2) SELECT * FROM some_cte"
    fixed_alias, warnings_alias = expand_select_star(sql_alias_cols, "ansi")
    assert not warnings_alias
    assert fixed_alias == "WITH some_cte(col_a, col_b) AS (SELECT 1, 2) SELECT col_a, col_b FROM some_cte"


def test_expand_select_star_multi_cte_cascade():
    models = {
        "raw_tbl": {"id": "INT", "val": "TEXT"},
    }
    sql = (
        "WITH cte1 AS (SELECT * FROM raw_tbl), "
        "cte2 AS (SELECT * FROM cte1) "
        "SELECT * FROM cte2"
    )
    fixed, warnings = expand_select_star(sql, "ansi", models)
    assert not warnings
    assert fixed == (
        "WITH cte1 AS (SELECT id, val FROM raw_tbl), "
        "cte2 AS (SELECT id, val FROM cte1) "
        "SELECT id, val FROM cte2"
    )


def test_expand_select_star_joined_tables():
    models = {
        "users": {"id": "INT", "username": "TEXT"},
        "orders": {"id": "INT", "user_id": "INT", "total": "FLOAT"},
    }

    # Preserves table qualification for joined query
    sql = "SELECT * FROM users u JOIN orders o ON u.id = o.user_id"
    fixed, warnings = expand_select_star(sql, "ansi", models)
    assert not warnings
    assert fixed == "SELECT u.id, u.username, o.id, o.user_id, o.total FROM users AS u JOIN orders AS o ON u.id = o.user_id"

    # Preserves table qualification without alias
    sql_no_alias = "SELECT * FROM users JOIN orders ON users.id = orders.user_id"
    fixed_no_alias, warnings_no_alias = expand_select_star(sql_no_alias, "ansi", models)
    assert not warnings_no_alias
    assert fixed_no_alias == (
        "SELECT users.id, users.username, orders.id, orders.user_id, orders.total "
        "FROM users JOIN orders ON users.id = orders.user_id"
    )


def test_expand_select_star_table_star_projections():
    models = {
        "t1": ["col1", "col2"],
        "t2": ["col3", "col4"],
    }
    # Specific table qualification t1.*
    sql = "SELECT t1.*, t2.col3 FROM t1 JOIN t2 ON t1.col1 = t2.col3"
    fixed, warnings = expand_select_star(sql, "ansi", models)
    assert not warnings
    assert fixed == "SELECT t1.col1, t1.col2, t2.col3 FROM t1 JOIN t2 ON t1.col1 = t2.col3"

    # Single table explicit qualification t.*
    sql_single = "SELECT t.* FROM t1 AS t"
    fixed_single, warnings_single = expand_select_star(sql_single, "ansi", models)
    assert not warnings_single
    assert fixed_single == "SELECT t.col1, t.col2 FROM t1 AS t"

    # Specific table qualification with unknown table
    sql_unknown = "SELECT t_missing.* FROM t1"
    fixed_unknown, warnings_unknown = expand_select_star(sql_unknown, "ansi", models, "my_model")
    assert fixed_unknown == sql_unknown
    assert warnings_unknown == [
        "Skipped SELECT * expansion for my_model: upstream schema for t_missing is not available statically"
    ]


def test_expand_select_star_uncataloged_fallback():
    # 1. External uncataloged table
    sql = "SELECT * FROM raw_external_table"
    fixed, warnings = expand_select_star(sql, "ansi", {}, "my_model")
    assert fixed == sql
    assert warnings == [
        "Skipped SELECT * expansion for my_model: upstream schema for raw_external_table is not available statically"
    ]

    # 2. Model exists in registry but has empty columns_to_types
    empty_model = ModelRepresentation(
        name="undocumented",
        path="models/undoc.sql",
        dialect="duckdb",
        columns_to_types={},
    )
    sql2 = "SELECT * FROM undocumented"
    fixed2, warnings2 = expand_select_star(sql2, "duckdb", {"undocumented": empty_model}, "my_model")
    assert fixed2 == sql2
    assert warnings2 == [
        "Skipped SELECT * expansion for my_model: upstream schema for undocumented is not available statically"
    ]

    # 3. Joined query where one table is uncataloged
    cataloged = ModelRepresentation(
        name="cat_table",
        path="models/cat.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    sql3 = "SELECT * FROM cat_table JOIN raw_source ON cat_table.id = raw_source.id"
    fixed3, warnings3 = expand_select_star(sql3, "duckdb", {"cat_table": cataloged}, "reporting_model")
    assert fixed3 == sql3
    assert warnings3 == [
        "Skipped SELECT * expansion for reporting_model: upstream schema for raw_source is not available statically"
    ]

    # 4. CTE referencing uncataloged source
    sql4 = "WITH cte AS (SELECT * FROM raw_source) SELECT * FROM cte"
    fixed4, warnings4 = expand_select_star(sql4, "duckdb", {}, "model_with_cte")
    assert fixed4 == sql4
    assert warnings4 == [
        "Skipped SELECT * expansion for model_with_cte: upstream schema for raw_source is not available statically"
    ]

    # 5. SELECT * without sources
    sql5 = "SELECT *"
    fixed5, warnings5 = expand_select_star(sql5, "ansi", {})
    assert fixed5 == sql5
    assert warnings5 == [
        "Skipped SELECT * expansion for model: upstream schema is not available statically"
    ]


def test_expand_select_star_preserves_count_and_syntax():
    models = {"tbl": ["id", "val"]}

    # COUNT(*) should remain untouched
    sql_count = "SELECT COUNT(*) FROM tbl"
    fixed_count, warnings_count = expand_select_star(sql_count, "ansi", models)
    assert fixed_count == sql_count
    assert not warnings_count

    # COUNT(DISTINCT *) untouched
    sql_distinct = "SELECT COUNT(DISTINCT *) FROM tbl"
    fixed_distinct, warnings_distinct = expand_select_star(sql_distinct, "ansi", models)
    assert fixed_distinct == sql_distinct
    assert not warnings_distinct

    # COUNT(*) with wildcard *
    sql_combo = "SELECT COUNT(*), * FROM tbl"
    fixed_combo, warnings_combo = expand_select_star(sql_combo, "ansi", models)
    assert not warnings_combo
    assert fixed_combo == "SELECT COUNT(*), id, val FROM tbl"

    # Non-star expressions preserved around *
    sql_expr = "SELECT 1 AS const, *, UPPER(val) AS upper_val FROM tbl"
    fixed_expr, warnings_expr = expand_select_star(sql_expr, "ansi", models)
    assert not warnings_expr
    assert fixed_expr == "SELECT 1 AS const, id, val, UPPER(val) AS upper_val FROM tbl"


def test_expand_select_star_edge_cases():
    # Non-SELECT statement
    sql_insert = "INSERT INTO tbl VALUES (1, 'a')"
    fixed_insert, warnings_insert = expand_select_star(sql_insert, "ansi", {})
    assert fixed_insert == sql_insert
    assert not warnings_insert

    # Invalid SQL syntax
    sql_invalid = "SELECT FROM WHERE"
    fixed_invalid, warnings_invalid = expand_select_star(sql_invalid, "ansi", {})
    assert fixed_invalid == sql_invalid
    assert not warnings_invalid

    # Plain query without *
    sql_plain = "SELECT id, val FROM tbl"
    fixed_plain, warnings_plain = expand_select_star(sql_plain, "ansi", {})
    assert fixed_plain == sql_plain
    assert not warnings_plain

    # Subquery in FROM
    sql_subquery = "SELECT * FROM (SELECT 1 AS a, 2 AS b) sub"
    fixed_subquery, warnings_subquery = expand_select_star(sql_subquery, "ansi", {})
    assert not warnings_subquery
    assert fixed_subquery == "SELECT a, b FROM (SELECT 1 AS a, 2 AS b) AS sub"


def test_apply_autofixes_banselectstar(tmp_path: Path):
    sql_file = tmp_path / "models/clean_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM upstream", encoding="utf-8")

    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            model="clean_model",
            path="models/clean_model.sql",
            message="clean_model: SELECT * is prohibited",
        )
    ]

    models = {
        "upstream": ModelRepresentation(
            name="upstream",
            path="models/upstream.sql",
            dialect="duckdb",
            columns_to_types={"id": "INT", "name": "TEXT"},
        ),
        "clean_model": ModelRepresentation(
            name="clean_model",
            path=str(sql_file),
            dialect="duckdb",
        ),
    }

    # 1. Successfully expanded
    logs = apply_autofixes(tmp_path, "sqlmesh", findings, models)
    assert any("Expanded SELECT * in clean_model.sql" in log for log in logs)
    assert sql_file.read_text(encoding="utf-8") == "SELECT id, name FROM upstream"

    # 2. Rerun when already fixed is a no-op
    logs_noop = apply_autofixes(tmp_path, "sqlmesh", findings, models)
    assert not any("Expanded SELECT *" in log for log in logs_noop)

    # 3. Uncataloged source fallback skips modification
    bad_file = tmp_path / "models/bad_model.sql"
    bad_file.write_text("SELECT * FROM raw_external", encoding="utf-8")
    bad_findings = [
        LintFinding(
            check="ban_select_star",
            severity="error",
            model="bad_model",
            path="models/bad_model.sql",
            message="SELECT * prohibited",
        )
    ]
    models["bad_model"] = ModelRepresentation(
        name="bad_model",
        path=str(bad_file),
        dialect="duckdb",
    )
    bad_logs = apply_autofixes(tmp_path, "sqlmesh", bad_findings, models)
    assert bad_file.read_text(encoding="utf-8") == "SELECT * FROM raw_external"
    assert any("Skipped SELECT * expansion for bad_model: upstream schema for raw_external is not available statically" in log for log in bad_logs)

    # 4. Exception during write logs failure
    sql_file.chmod(0o444)
    try:
        sql_file.chmod(0o644)
        sql_file.write_text("SELECT * FROM upstream", encoding="utf-8")
        sql_file.chmod(0o444)
        fail_logs = apply_autofixes(tmp_path, "sqlmesh", findings, models)
        assert any("Failed to expand SELECT * in clean_model.sql" in log for log in fail_logs)
    finally:
        sql_file.chmod(0o644)


def test_expand_select_star_coverage_edge_cases():
    # 1. Empty string parses to None
    fixed_empty, warnings_empty = expand_select_star("")
    assert fixed_empty == ""
    assert not warnings_empty

    # 2. Table macro placeholder not matching ref/source
    sql_macro = "SELECT * FROM @custom_func()"
    fixed_macro, warnings_macro = expand_select_star(sql_macro)
    assert fixed_macro == sql_macro
    assert warnings_macro == [
        "Skipped SELECT * expansion for model: upstream schema for @custom_func() is not available statically"
    ]

    # 3. Model matched by v.name when dict key differs
    m1 = ModelRepresentation(
        name="orders",
        path="m.sql",
        dialect="ansi",
        columns_to_types={"id": "INT"},
    )
    models1 = {"dict_key_differs": m1}
    fixed_m1, warnings_m1 = expand_select_star("SELECT * FROM orders", "ansi", models1)
    assert not warnings_m1
    assert fixed_m1 == "SELECT id FROM orders"

    # 4. Model matched by normalize_model_name
    m2 = ModelRepresentation(
        name="catalog.db.users",
        path="u.sql",
        dialect="ansi",
        columns_to_types={"id": "INT"},
    )
    models2 = {"k": m2}
    fixed_m2, warnings_m2 = expand_select_star("SELECT * FROM db.users", "ansi", models2)
    assert not warnings_m2
    assert fixed_m2 == "SELECT id FROM db.users"

    # 4b. Model matched by short name when cand has only basename
    m2b = ModelRepresentation(
        name="some_schema.items",
        path="i.sql",
        dialect="ansi",
        columns_to_types={"item_id": "INT"},
    )
    models2b = {"k": m2b}
    fixed_m2b, warnings_m2b = expand_select_star("SELECT * FROM items", "ansi", models2b)
    assert not warnings_m2b
    assert fixed_m2b == "SELECT item_id FROM items"

    # 5. Model lookup where entry is dict (v_name is None) and cand is unknown
    models_dict = {"other": {"a": "int"}}
    fixed_unk, warnings_unk = expand_select_star("SELECT * FROM missing_tbl", "ansi", models_dict)
    assert fixed_unk == "SELECT * FROM missing_tbl"
    assert warnings_unk == [
        "Skipped SELECT * expansion for model: upstream schema for missing_tbl is not available statically"
    ]

    # 6. Specific table qualification on subquery: SELECT sub.* FROM (SELECT 1 AS a) sub
    sql_sub_star = "SELECT sub.* FROM (SELECT 1 AS a) sub"
    fixed_sub_star, warnings_sub_star = expand_select_star(sql_sub_star, "ansi")
    assert not warnings_sub_star
    assert fixed_sub_star == "SELECT sub.a FROM (SELECT 1 AS a) AS sub"

    # 7. Specific table qualification t.* on table with empty schema
    empty_m = ModelRepresentation(name="undoc", path="u.sql", dialect="ansi", columns_to_types={})
    fixed_t_empty, warnings_t_empty = expand_select_star(
        "SELECT t.* FROM undoc t", "ansi", {"undoc": empty_m}
    )
    assert fixed_t_empty == "SELECT t.* FROM undoc t"
    assert warnings_t_empty == [
        "Skipped SELECT * expansion for model: upstream schema for undoc is not available statically"
    ]

    # 8. Unnest source
    fixed_unnest, warnings_unnest = expand_select_star("SELECT * FROM UNNEST([1, 2])", "duckdb")
    assert fixed_unnest == "SELECT * FROM UNNEST([1, 2])"
    assert warnings_unnest == [
        "Skipped SELECT * expansion for model: upstream schema for unknown is not available statically"
    ]

    # 9. Star in WHERE predicate rather than SELECT projection (not modified)
    fixed_pred, warnings_pred = expand_select_star("SELECT 1 FROM t WHERE x = *")
    assert fixed_pred == "SELECT 1 FROM t WHERE x = *"
    assert not warnings_pred


def test_apply_autofixes_banselectstar_missing_model_name(tmp_path: Path):
    sql_file = tmp_path / "models/no_name_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM upstream", encoding="utf-8")

    # finding has model=None
    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            model=None,
            path="models/no_name_model.sql",
            message="SELECT * is prohibited",
        )
    ]

    models = {
        "upstream": ModelRepresentation(
            name="upstream",
            path="models/upstream.sql",
            dialect="duckdb",
            columns_to_types={"id": "INT"},
        ),
        "no_name_model": ModelRepresentation(
            name="inferred_model_name",
            path=str(sql_file),
            dialect="duckdb",
        ),
    }

    logs = apply_autofixes(tmp_path, "sqlmesh", findings, models)
    assert any("Expanded SELECT * in no_name_model.sql" in log for log in logs)
    assert sql_file.read_text(encoding="utf-8") == "SELECT id FROM upstream"


def test_find_matching_paren():
    assert _find_matching_paren("MODEL ()", 6) == 7
    assert _find_matching_paren("MODEL (grain (a, b))", 6) == 19
    assert _find_matching_paren("MODEL (name 'foo)')", 6) == 18
    assert _find_matching_paren('MODEL (name "foo)")', 6) == 18
    assert _find_matching_paren("MODEL (name `foo)`)", 6) == 18
    assert _find_matching_paren("MODEL (\n-- comment (skip)\nname x\n)", 6) == 33
    assert _find_matching_paren("MODEL (/* comment (skip) */ name x)", 6) == 34
    assert _find_matching_paren('MODEL (name "a\\"b")', 6) == 18
    assert _find_matching_paren("MODEL (-- unclosed comment", 6) == -1
    assert _find_matching_paren("MODEL (/* unclosed block", 6) == -1
    assert _find_matching_paren("MODEL (", 6) == -1
    assert _find_matching_paren("MODEL ()", -1) == -1
    assert _find_matching_paren("MODEL ()", 0) == -1


def test_sync_sqlmesh_model_name():
    # 1. Unqualified name
    sql1 = "MODEL (name old_name);\nSELECT 1;"
    assert sync_sqlmesh_model_name(sql1, "new_name") == "MODEL (name new_name);\nSELECT 1;"

    # 2. Schema-qualified name
    sql2 = "MODEL (name marketing.old_name);\nSELECT 1;"
    assert sync_sqlmesh_model_name(sql2, "new_name") == "MODEL (name marketing.new_name);\nSELECT 1;"

    # 3. Double-quoted identifier
    sql3 = 'MODEL (name "marketing"."old_name");\nSELECT 1;'
    assert sync_sqlmesh_model_name(sql3, "new_name") == 'MODEL (name "marketing"."new_name");\nSELECT 1;'

    # 4. Single-quoted identifier
    sql4 = "MODEL (name 'marketing'.'old_name');\nSELECT 1;"
    assert sync_sqlmesh_model_name(sql4, "new_name") == "MODEL (name 'marketing'.'new_name');\nSELECT 1;"

    # 5. Backtick identifier
    sql5 = "MODEL (name `marketing`.`old_name`);\nSELECT 1;"
    assert sync_sqlmesh_model_name(sql5, "new_name") == "MODEL (name `marketing`.`new_name`);\nSELECT 1;"

    # 6. Multiline with other args and nested parens
    sql6 = """MODEL (
  name marketing.old_name,
  kind FULL,
  grain (id, sub_id)
);
SELECT 1;"""
    expected6 = """MODEL (
  name marketing.new_name,
  kind FULL,
  grain (id, sub_id)
);
SELECT 1;"""
    assert sync_sqlmesh_model_name(sql6, "new_name") == expected6

    # 7. No name parameter in MODEL block
    sql7 = "MODEL (\n  kind FULL\n);\nSELECT 1;"
    assert "name new_name," in sync_sqlmesh_model_name(sql7, "new_name")

    # 8. No MODEL block
    sql8 = "SELECT 1;"
    assert sync_sqlmesh_model_name(sql8, "new_name") == "SELECT 1;"

    # 9. Already matching
    sql9 = "MODEL (name marketing.new_name);\nSELECT 1;"
    assert sync_sqlmesh_model_name(sql9, "new_name") == sql9

    # 10. Unclosed MODEL block
    sql10 = "MODEL (name old_name"
    assert sync_sqlmesh_model_name(sql10, "new_name") == sql10


def test_sync_dataform_model_name():
    # 1. Double quoted
    df1 = 'config {\n  type: "view",\n  name: "old_name"\n}\nSELECT 1'
    assert sync_dataform_model_name(df1, "new_name") == 'config {\n  type: "view",\n  name: "new_name"\n}\nSELECT 1'

    # 2. Single quoted
    df2 = "config {\n  name: 'old_name'\n}\nSELECT 1"
    assert sync_dataform_model_name(df2, "new_name") == "config {\n  name: 'new_name'\n}\nSELECT 1"

    # 3. Unquoted
    df3 = "config {\n  name: old_name\n}\nSELECT 1"
    assert sync_dataform_model_name(df3, "new_name") == 'config {\n  name: "new_name"\n}\nSELECT 1'

    # 4. Already matching
    df4 = 'config {\n  name: "new_name"\n}\nSELECT 1'
    assert sync_dataform_model_name(df4, "new_name") == df4

    # 5. No config block
    df5 = "SELECT 1"
    assert sync_dataform_model_name(df5, "new_name") == "SELECT 1"

    # 6. No name parameter in config
    df6 = 'config {\n  type: "view"\n}\nSELECT 1'
    assert sync_dataform_model_name(df6, "new_name") == df6

    # 7. Unclosed config block
    df7 = 'config { name: "old_name"'
    assert sync_dataform_model_name(df7, "new_name") == df7


def test_apply_autofixes_mart_naming_sqlmesh(tmp_path: Path):
    model_file = tmp_path / "models/marts/marketing/ad_performance.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(
        "MODEL (\n  name marketing.ad_performance,\n  kind FULL\n);\nSELECT 1 AS id;",
        encoding="utf-8",
    )

    findings = [
        LintFinding(
            check="martmodelnamingconvention",
            severity="error",
            model="marketing.ad_performance",
            path="models/marts/marketing/ad_performance.sql",
            message="Model 'ad_performance' in mart 'marketing' should start with 'marketing_'.",
        )
    ]
    models = {
        "marketing.ad_performance": ModelRepresentation(
            name="marketing.ad_performance",
            path=str(model_file),
            dialect="duckdb",
        )
    }

    logs = apply_autofixes(tmp_path, "sqlmesh", findings, models)
    assert "Renamed model file ad_performance.sql -> marketing_ad_performance.sql" in logs

    # Verify original file no longer exists and new file exists
    assert not model_file.exists()
    renamed_file = tmp_path / "models/marts/marketing/marketing_ad_performance.sql"
    assert renamed_file.exists()

    content = renamed_file.read_text(encoding="utf-8")
    assert "name marketing.marketing_ad_performance" in content


def test_apply_autofixes_mart_naming_dataform(tmp_path: Path):
    sqlx_file = tmp_path / "definitions/marts/finance/revenue.sqlx"
    sqlx_file.parent.mkdir(parents=True, exist_ok=True)
    sqlx_file.write_text(
        'config {\n  type: "table",\n  name: "revenue"\n}\nSELECT 100 AS amount',
        encoding="utf-8",
    )

    findings = [
        LintFinding(
            check="mart_naming",
            severity="error",
            model="revenue",
            path="definitions/marts/finance/revenue.sqlx",
            message="Model 'revenue' in mart 'finance' should start with 'finance_'.",
        )
    ]
    models = {
        "revenue": ModelRepresentation(
            name="revenue",
            path=str(sqlx_file),
            dialect="bigquery",
        )
    }

    logs = apply_autofixes(tmp_path, "dataform", findings, models)
    assert "Renamed model file revenue.sqlx -> finance_revenue.sqlx" in logs

    assert not sqlx_file.exists()
    renamed_file = tmp_path / "definitions/marts/finance/finance_revenue.sqlx"
    assert renamed_file.exists()

    content = renamed_file.read_text(encoding="utf-8")
    assert 'name: "finance_revenue"' in content


def test_apply_autofixes_mart_naming_dbt(tmp_path: Path):
    model_file = tmp_path / "models/marts/core/customers.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT * FROM {{ ref('stg_customers') }}", encoding="utf-8")

    schema_file = tmp_path / "models/marts/core/schema.yml"
    schema_file.write_text(
        yaml.safe_dump({
            "version": 2,
            "models": [{"name": "customers", "description": "Customer mart"}],
        }),
        encoding="utf-8",
    )

    findings = [
        LintFinding(
            check="martmodelnamingconvention",
            severity="error",
            model="customers",
            path="models/marts/core/customers.sql",
            message="Model 'customers' in mart 'core' should start with 'core_'.",
        )
    ]
    models = {
        "customers": ModelRepresentation(
            name="customers",
            path=str(model_file),
            dialect="ansi",
        )
    }

    logs = apply_autofixes(tmp_path, "dbt", findings, models)
    assert "Renamed model file customers.sql -> core_customers.sql" in logs

    assert not model_file.exists()
    renamed_file = tmp_path / "models/marts/core/core_customers.sql"
    assert renamed_file.exists()

    schema_data = yaml.safe_load(schema_file.read_text(encoding="utf-8"))
    assert schema_data["models"][0]["name"] == "core_customers"


def test_apply_autofixes_mart_naming_destination_exists_non_destructive(tmp_path: Path):
    model_file = tmp_path / "models/marts/marketing/ad_performance.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT 1 AS orig;", encoding="utf-8")

    dest_file = tmp_path / "models/marts/marketing/marketing_ad_performance.sql"
    dest_file.write_text("SELECT 2 AS existing;", encoding="utf-8")

    findings = [
        LintFinding(
            check="martmodelnamingconvention",
            severity="error",
            model="ad_performance",
            path="models/marts/marketing/ad_performance.sql",
            message="Model 'ad_performance' in mart 'marketing' should start with 'marketing_'.",
        )
    ]
    models = {
        "ad_performance": ModelRepresentation(
            name="ad_performance",
            path=str(model_file),
            dialect="ansi",
        )
    }

    logs = apply_autofixes(tmp_path, "dbt", findings, models)
    assert any("already exists" in log for log in logs)

    # Both files must remain unchanged
    assert model_file.exists()
    assert model_file.read_text(encoding="utf-8") == "SELECT 1 AS orig;"
    assert dest_file.exists()
    assert dest_file.read_text(encoding="utf-8") == "SELECT 2 AS existing;"


def test_apply_autofixes_mart_naming_with_custom_layer_name(tmp_path: Path):
    from tff.core.config import FitnessFunctionsConfig

    config = FitnessFunctionsConfig()
    config.rules.mart_naming.layer_name = "data_marts"

    model_file = tmp_path / "models/data_marts/ops/metrics.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT 1 AS m;", encoding="utf-8")

    findings = [
        LintFinding(
            check="martmodelnamingconvention",
            severity="error",
            model="metrics",
            path="models/data_marts/ops/metrics.sql",
            message="Model 'metrics' in mart 'ops' should start with 'ops_'.",
        )
    ]
    models = {
        "metrics": ModelRepresentation(
            name="metrics",
            path=str(model_file),
            dialect="ansi",
        )
    }

    logs = apply_autofixes(tmp_path, "dbt", findings, models, config=config)
    assert "Renamed model file metrics.sql -> ops_metrics.sql" in logs

    assert not model_file.exists()
    assert (tmp_path / "models/data_marts/ops/ops_metrics.sql").exists()


def test_apply_autofixes_filename_equals_modelname_sqlmesh(tmp_path: Path):
    model_file = tmp_path / "models/marts/marketing/marketing_ad_performance.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(
        "MODEL (\n  name marketing.mismatched_name\n);\nSELECT 1;",
        encoding="utf-8",
    )

    findings = [
        LintFinding(
            check="filenameequalsmodelname",
            severity="error",
            model="marketing.mismatched_name",
            path="models/marts/marketing/marketing_ad_performance.sql",
            message="Model name differs from filename.",
        )
    ]
    models = {
        "marketing.mismatched_name": ModelRepresentation(
            name="marketing.mismatched_name",
            path=str(model_file),
            dialect="duckdb",
        )
    }

    logs = apply_autofixes(tmp_path, "sqlmesh", findings, models)
    assert "Synchronized model name to 'marketing_ad_performance' in marketing_ad_performance.sql" in logs

    content = model_file.read_text(encoding="utf-8")
    assert "name marketing.marketing_ad_performance" in content


def test_apply_autofixes_filename_equals_modelname_dataform(tmp_path: Path):
    sqlx_file = tmp_path / "definitions/marts/finance/finance_revenue.sqlx"
    sqlx_file.parent.mkdir(parents=True, exist_ok=True)
    sqlx_file.write_text(
        'config {\n  type: "table",\n  name: "wrong_rev"\n}\nSELECT 1',
        encoding="utf-8",
    )

    findings = [
        LintFinding(
            check="filename_equals_modelname",
            severity="error",
            model="wrong_rev",
            path="definitions/marts/finance/finance_revenue.sqlx",
            message="Model name differs from filename.",
        )
    ]
    models = {
        "wrong_rev": ModelRepresentation(
            name="wrong_rev",
            path=str(sqlx_file),
            dialect="bigquery",
        )
    }

    logs = apply_autofixes(tmp_path, "dataform", findings, models)
    assert "Synchronized model name to 'finance_revenue' in finance_revenue.sqlx" in logs

    content = sqlx_file.read_text(encoding="utf-8")
    assert 'name: "finance_revenue"' in content


def test_apply_autofixes_mart_and_filename_sync_combined(tmp_path: Path):
    model_file = tmp_path / "models/marts/marketing/ad_performance.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text(
        "MODEL (\n  name marketing.arbitrary_name\n);\nSELECT 1;",
        encoding="utf-8",
    )

    findings = [
        LintFinding(
            check="martmodelnamingconvention",
            severity="error",
            model="marketing.arbitrary_name",
            path="models/marts/marketing/ad_performance.sql",
            message="Model 'ad_performance' in mart 'marketing' should start with 'marketing_'.",
        ),
        LintFinding(
            check="filenameequalsmodelname",
            severity="error",
            model="marketing.arbitrary_name",
            path="models/marts/marketing/ad_performance.sql",
            message="Model name differs from filename.",
        ),
    ]
    models = {
        "marketing.arbitrary_name": ModelRepresentation(
            name="marketing.arbitrary_name",
            path=str(model_file),
            dialect="duckdb",
        )
    }

    logs = apply_autofixes(tmp_path, "sqlmesh", findings, models)
    assert "Renamed model file ad_performance.sql -> marketing_ad_performance.sql" in logs
    # Should not duplicate logs
    assert not any("Synchronized model name" in log for log in logs)

    renamed_file = tmp_path / "models/marts/marketing/marketing_ad_performance.sql"
    assert renamed_file.exists()
    assert "name marketing.marketing_ad_performance" in renamed_file.read_text(encoding="utf-8")


def test_apply_autofixes_rename_and_sync_error_handling(tmp_path: Path):
    model_file = tmp_path / "models/marts/marketing/ad_performance.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("MODEL (name x); SELECT 1;", encoding="utf-8")

    findings = [
        LintFinding(
            check="martmodelnamingconvention",
            severity="error",
            model="x",
            path="models/marts/marketing/ad_performance.sql",
            message="Model 'ad_performance' in mart 'marketing' should start with 'marketing_'.",
        )
    ]
    models = {
        "x": ModelRepresentation(
            name="x",
            path=str(model_file),
            dialect="duckdb",
        )
    }

    # Simulate error during rename
    with patch.object(Path, "rename", side_effect=OSError("Disk write protected")):
        logs = apply_autofixes(tmp_path, "sqlmesh", findings, models)
        assert any("Failed to rename ad_performance.sql" in log for log in logs)

    # Simulate error during sync
    findings_sync = [
        LintFinding(
            check="filenameequalsmodelname",
            severity="error",
            model="x",
            path="models/marts/marketing/ad_performance.sql",
            message="Model name differs.",
        )
    ]
    with patch.object(Path, "write_text", side_effect=OSError("Permission denied")):
        logs_sync = apply_autofixes(tmp_path, "sqlmesh", findings_sync, models)
        assert any("Failed to synchronize model name in ad_performance.sql" in log for log in logs_sync)


def test_sync_dbt_schema_yaml_edge_cases(tmp_path: Path):
    # 1. Broken YAML
    (tmp_path / "broken.yml").write_text("bad: yaml: [", encoding="utf-8")
    # 2. YAML without models
    (tmp_path / "other.yml").write_text("version: 2\nsources: []", encoding="utf-8")
    # 3. Normal schema file
    schema_file = tmp_path / "schema.yml"
    schema_file.write_text("version: 2\nmodels:\n  - name: old_m\n", encoding="utf-8")

    # Should safely skip broken and non-models YAML, and update schema.yml
    _sync_dbt_schema_yaml_model_name(tmp_path, "old_m", "new_m")
    assert "name: new_m" in schema_file.read_text(encoding="utf-8")

    # 4. Dump exception
    with patch("ruamel.yaml.YAML.dump", side_effect=Exception("Dump error")):
        _sync_dbt_schema_yaml_model_name(tmp_path, "new_m", "another_m")


def test_apply_autofixes_mart_naming_message_fallback(tmp_path: Path):
    # Path without "marts" in parts
    model_file = tmp_path / "models/analytics/user_engagement.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT 1 AS engagement;", encoding="utf-8")

    findings = [
        LintFinding(
            check="martmodelnamingconvention",
            severity="error",
            model="user_engagement",
            path="models/analytics/user_engagement.sql",
            message="Model 'user_engagement' in mart 'marketing' should start with 'marketing_'.",
        )
    ]
    models = {
        "user_engagement": ModelRepresentation(
            name="user_engagement",
            path=str(model_file),
            dialect="ansi",
        )
    }

    logs = apply_autofixes(tmp_path, "dbt", findings, models)
    assert "Renamed model file user_engagement.sql -> marketing_user_engagement.sql" in logs
    assert (tmp_path / "models/analytics/marketing_user_engagement.sql").exists()


def test_apply_autofixes_filename_equals_modelname_plain_sql(tmp_path: Path):
    model_file = tmp_path / "models/plain.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT 1 AS id;", encoding="utf-8")

    findings = [
        LintFinding(
            check="filenameequalsmodelname",
            severity="error",
            model="plain",
            path="models/plain.sql",
            message="Model name mismatch.",
        )
    ]
    models = {
        "plain": ModelRepresentation(
            name="plain",
            path=str(model_file),
            dialect="ansi",
        )
    }

    # Calling for plain dbt without MODEL block triggers else branch (content unchanged)
    logs = apply_autofixes(tmp_path, "dbt", findings, models)
    assert logs == []

def test_fix_positional_clauses_selective():
    sql = "SELECT a, b FROM table GROUP BY 1, 2 ORDER BY 1 DESC"

    # Only fix GROUP BY
    fixed_group = fix_positional_clauses(sql, "ansi", fix_group_by=True, fix_order_by=False)
    assert fixed_group == "SELECT a, b FROM table GROUP BY a, b ORDER BY 1 DESC"

    # Only fix ORDER BY
    fixed_order = fix_positional_clauses(sql, "ansi", fix_group_by=False, fix_order_by=True)
    assert fixed_order == "SELECT a, b FROM table GROUP BY 1, 2 ORDER BY a DESC"

    # Fix neither
    fixed_none = fix_positional_clauses(sql, "ansi", fix_group_by=False, fix_order_by=False)
    assert fixed_none == sql


def test_apply_autofixes_individual_positional_checks(tmp_path: Path):
    sql_file = tmp_path / "model.sql"
    sql_file.write_text("SELECT a, b FROM table GROUP BY 1, 2 ORDER BY 1 DESC", encoding="utf-8")

    models = {
        "model": ModelRepresentation(
            name="model",
            path=str(sql_file),
            dialect="ansi",
        )
    }

    # 1. Autofix only nopositionalgroupby
    findings_group = [
        LintFinding(
            check="nopositionalgroupby",
            severity="error",
            model="model",
            path="model.sql",
            message="2 positional GROUP BY references found",
        )
    ]
    logs_group = apply_autofixes(tmp_path, "dbt", findings_group, models)
    assert len(logs_group) == 1
    assert "Fixed positional GROUP BY in model.sql" in logs_group[0]
    assert sql_file.read_text(encoding="utf-8") == "SELECT a, b FROM table GROUP BY a, b ORDER BY 1 DESC"

    # 2. Autofix only nopositionalorderby
    findings_order = [
        LintFinding(
            check="nopositionalorderby",
            severity="error",
            model="model",
            path="model.sql",
            message="1 positional ORDER BY reference found",
        )
    ]
    logs_order = apply_autofixes(tmp_path, "dbt", findings_order, models)
    assert len(logs_order) == 1
    assert "Fixed positional ORDER BY in model.sql" in logs_order[0]
    assert sql_file.read_text(encoding="utf-8") == "SELECT a, b FROM table GROUP BY a, b ORDER BY a DESC"






