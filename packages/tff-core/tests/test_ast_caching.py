from pathlib import Path
import json
from unittest.mock import MagicMock
import pytest
import sqlglot
import sqlglot.expressions as exp
from sqlmesh.core.model import Model as SqlMeshModel

from tff.core.model import ModelRepresentation
from tff.dbt.manifest import load_dbt_models
from tff.sqlmesh.loader import map_sqlmesh_model


def test_model_representation_ast_lazy_parsing() -> None:
    # 1. Test lazy parsing from query string
    model = ModelRepresentation(
        name="test_model",
        path="dummy_path.sql",
        dialect="duckdb",
        query="SELECT * FROM my_table",
    )
    assert model.expression is None
    
    # Access .ast
    ast = model.ast
    assert ast is not None
    assert isinstance(ast, exp.Expression)
    assert model.expression is ast

    # Verify that accessing .ast again returns the exact same object (cached)
    assert model.ast is ast


def test_model_representation_ast_lazy_parsing_from_file(tmp_path: Path) -> None:
    # 2. Test lazy parsing by reading file
    sql_file = tmp_path / "model.sql"
    sql_file.write_text("SELECT a, b FROM table_name", encoding="utf-8")
    
    model = ModelRepresentation(
        name="file_model",
        path=str(sql_file),
        dialect="duckdb",
        query=None,
    )
    assert model.expression is None
    
    ast = model.ast
    assert ast is not None
    assert isinstance(ast, exp.Expression)
    assert model.expression is ast
    assert model.ast is ast


def test_model_representation_ast_lazy_parsing_file_not_found() -> None:
    model = ModelRepresentation(
        name="nonexistent_file_model",
        path="nonexistent_file.sql",
        dialect="duckdb",
        query=None,
    )
    assert model.ast is None


def test_model_representation_ast_lazy_parsing_read_exception() -> None:
    # Use a directory path to trigger a read exception when read_text is called
    model = ModelRepresentation(
        name="directory_model",
        path=".",
        dialect="duckdb",
        query=None,
    )
    assert model.ast is None


def test_model_representation_ast_strip_model_block() -> None:
    # Test that SQLMesh MODEL block is stripped during lazy parsing
    model = ModelRepresentation(
        name="mesh_model",
        path="dummy.sql",
        dialect="duckdb",
        query="MODEL (name mesh_model); SELECT 1;",
    )
    ast = model.ast
    assert ast is not None
    assert model.expression is ast
    # The AST should represent "SELECT 1"
    assert ast.sql(dialect="duckdb") == "SELECT 1"


def test_model_representation_ast_invalid_sql() -> None:
    # Test that invalid SQL returns None and doesn't crash
    model = ModelRepresentation(
        name="invalid_model",
        path="dummy.sql",
        dialect="duckdb",
        query="SELECT FROM WHERE;",
    )
    assert model.ast is None


def test_dbt_loader_populates_expression(tmp_path: Path) -> None:
    # Test that dbt loader populates the expression attribute
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    manifest_data = {
        "nodes": {
            "model.my_project.stg_users": {
                "resource_type": "model",
                "name": "stg_users",
                "original_file_path": "models/staging/stg_users.sql",
                "columns": {},
                "config": {
                    "materialized": "view",
                },
                "compiled_code": "SELECT id, name FROM raw_users",
                "depends_on": {"nodes": []}
            }
        },
        "sources": {},
        "metadata": {
            "adapter_type": "duckdb"
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dbt_models(tmp_path)
    assert "model.my_project.stg_users" in models
    model_rep = models["model.my_project.stg_users"]
    assert model_rep.expression is not None
    assert isinstance(model_rep.expression, exp.Expression)
    assert model_rep.ast is model_rep.expression


def test_dbt_loader_handles_invalid_expression(tmp_path: Path) -> None:
    # Test that dbt loader handles invalid expression without raising error
    target_dir = tmp_path / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest_file = target_dir / "manifest.json"

    manifest_data = {
        "nodes": {
            "model.my_project.stg_users": {
                "resource_type": "model",
                "name": "stg_users",
                "original_file_path": "models/staging/stg_users.sql",
                "columns": {},
                "config": {
                    "materialized": "view",
                },
                "compiled_code": "SELECT FROM WHERE;",
                "depends_on": {"nodes": []}
            }
        },
        "sources": {},
        "metadata": {
            "adapter_type": "duckdb"
        }
    }
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dbt_models(tmp_path)
    assert "model.my_project.stg_users" in models
    model_rep = models["model.my_project.stg_users"]
    assert model_rep.expression is None


def test_sqlmesh_loader_populates_expression() -> None:
    # Test that SQLMesh loader populates the expression attribute
    mock_model = MagicMock(spec=SqlMeshModel)
    mock_model.name = "my_model"
    mock_model._path = Path("models/my_model.sql")
    mock_model.dialect = "duckdb"
    mock_model.kind = MagicMock()
    mock_model.kind.is_symbolic = False
    mock_model.kind.name = "FULL"
    mock_model.kind.is_view = True
    mock_model.columns_to_types = {}
    mock_model.depends_on = set()
    mock_model.description = None
    mock_model.owner = None
    mock_model.grains = []
    mock_model.audits = []

    # Mock SQLMesh model.query as a sqlglot expression
    parsed_query = sqlglot.parse_one("SELECT * FROM table", read="duckdb")
    mock_model.query = parsed_query

    model_rep = map_sqlmesh_model(mock_model)
    assert model_rep.expression is parsed_query
    assert model_rep.ast is parsed_query
