import yaml
from pathlib import Path
from unittest.mock import patch
from tff.core.model import ModelRepresentation
from tff.core.report import LintFinding
from tff.core.autofix import (
    parse_model_block_args,
    fix_positional_clauses,
    fix_sqlmesh_metadata,
    fix_dbt_metadata,
    fix_dataform_metadata,
    _find_matching_brace,
    apply_autofixes,
    lift_nested_subqueries,
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




