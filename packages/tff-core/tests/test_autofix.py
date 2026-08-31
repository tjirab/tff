import yaml
from pathlib import Path
from tff.core.model import ModelRepresentation
from tff.core.report import LintFinding
from tff.core.autofix import (
    parse_model_block_args,
    fix_positional_clauses,
    fix_sqlmesh_metadata,
    fix_dbt_metadata,
    apply_autofixes,
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

