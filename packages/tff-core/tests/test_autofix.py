"""Unit tests for the curated tff autofix engine.

Verifies model declaration synchronization (filename_equals_modelname)
and atomic file writing safety guarantees across SQLMesh and Dataform.
"""

from __future__ import annotations

import stat
from pathlib import Path
from unittest.mock import patch
import pytest

from conftest import _make_finding
from tff.core.autofix import (
    _find_matching_brace,
    _find_matching_paren,
    apply_autofixes,
    atomic_write,
    atomic_write_text,
    sync_dataform_model_name,
    sync_sqlmesh_model_name,
)


# =============================================================================
# 1. ATOMIC WRITE TESTS
# =============================================================================


def test_atomic_write_creates_and_overwrites_file(tmp_path: Path):
    target = tmp_path / "subdir" / "test.txt"
    content = "Hello, world!"
    atomic_write(target, content)
    assert target.exists()
    assert target.read_text(encoding="utf-8") == content

    # Overwrite existing file
    new_content = "Updated content"
    atomic_write_text(target, new_content)
    assert target.read_text(encoding="utf-8") == new_content


def test_atomic_write_preserves_file_permissions(tmp_path: Path):
    target = tmp_path / "script.sh"
    target.write_text("echo hello\n", encoding="utf-8")
    target.chmod(0o755)

    atomic_write(target, "echo updated\n")
    current_mode = stat.S_IMODE(target.stat().st_mode)
    assert current_mode == 0o755


def test_atomic_write_directory_target_raises_error(tmp_path: Path):
    with pytest.raises(IsADirectoryError):
        atomic_write(tmp_path, "content")


def test_atomic_write_permission_denied_raises_error(tmp_path: Path):
    target = tmp_path / "readonly.txt"
    target.write_text("locked", encoding="utf-8")
    target.chmod(0o400)
    try:
        with patch("os.access", return_value=False):
            with pytest.raises(PermissionError):
                atomic_write(target, "new content")
    finally:
        target.chmod(0o600)


def test_atomic_write_cleans_up_temp_on_failure(tmp_path: Path):
    target = tmp_path / "fail.txt"
    target.write_text("initial", encoding="utf-8")

    with patch("pathlib.Path.replace", side_effect=OSError("Disk write failed")):
        with pytest.raises(OSError, match="Disk write failed"):
            atomic_write(target, "will fail")

    # Destination unchanged
    assert target.read_text(encoding="utf-8") == "initial"
    # No temporary .tmp files left behind in directory
    tmp_files = list(tmp_path.glob(".*.tmp"))
    assert len(tmp_files) == 0


def test_atomic_write_os_error_fallbacks(tmp_path: Path):
    """Exercise fallback branches for fsync and chmod/copymode failures."""
    target = tmp_path / "fallback.txt"
    with patch("os.fsync", side_effect=OSError("Not supported")), \
         patch("shutil.copymode", side_effect=OSError("chmod not supported")):
        target.write_text("initial", encoding="utf-8")
        atomic_write(target, "new content")
        assert target.read_text(encoding="utf-8") == "new content"

    target_new = tmp_path / "new_fallback.txt"
    with patch("os.chmod", side_effect=OSError("chmod not supported")):
        atomic_write(target_new, "created")
        assert target_new.read_text(encoding="utf-8") == "created"


# =============================================================================
# 2. BRACE AND PAREN PARSING TESTS
# =============================================================================


@pytest.mark.parametrize(
    "text,idx,expected",
    [
        ("{}", 0, 1),
        ("{ a { b } c }", 0, 12),
        ("{ '}' }", 0, 6),
        ('{ "}" }', 0, 6),
        ("{ `}` }", 0, 6),
        ('{ "escaped \\"}" }', 0, 16),
        ("{\n// comment }\n}", 0, 15),
        ("{\n// comment at EOF", 0, -1),
        ("{\n/* comment }\n*/ }", 0, 18),
        ("{\n/* unclosed comment", 0, -1),
        ("{ unclosed", 0, -1),
        ("invalid", 0, -1),
        ("{}", -1, -1),
        ("{}", 5, -1),
    ],
)
def test_find_matching_brace(text: str, idx: int, expected: int):
    assert _find_matching_brace(text, idx) == expected


@pytest.mark.parametrize(
    "text,idx,expected",
    [
        ("()", 0, 1),
        ("( a ( b ) c )", 0, 12),
        ("( ')' )", 0, 6),
        ('( ")" )', 0, 6),
        ("( `)` )", 0, 6),
        ('( "escaped \\")" )', 0, 16),
        ("(\n-- comment )\n)", 0, 15),
        ("(\n-- comment at EOF", 0, -1),
        ("(\n/* comment )\n*/ )", 0, 18),
        ("(\n/* unclosed comment", 0, -1),
        ("( unclosed", 0, -1),
        ("invalid", 0, -1),
        ("()", -1, -1),
        ("()", 5, -1),
    ],
)
def test_find_matching_paren(text: str, idx: int, expected: int):
    assert _find_matching_paren(text, idx) == expected


# =============================================================================
# 3. SQLMESH MODEL NAME SYNC TESTS
# =============================================================================


@pytest.mark.parametrize(
    "sql,new_name,expected",
    [
        (
            "MODEL (\n  name old_model,\n  kind FULL\n);\nSELECT 1",
            "new_model",
            "MODEL (\n  name new_model,\n  kind FULL\n);\nSELECT 1",
        ),
        (
            "MODEL (\n  name analytics.old_model,\n  kind FULL\n);\nSELECT 1",
            "new_model",
            "MODEL (\n  name analytics.new_model,\n  kind FULL\n);\nSELECT 1",
        ),
        (
            'MODEL (\n  name "analytics"."old_model",\n  kind FULL\n);\nSELECT 1',
            "new_model",
            'MODEL (\n  name "analytics"."new_model",\n  kind FULL\n);\nSELECT 1',
        ),
        (
            "MODEL (\n  name `analytics`.`old_model`,\n  kind FULL\n);\nSELECT 1",
            "new_model",
            "MODEL (\n  name `analytics`.`new_model`,\n  kind FULL\n);\nSELECT 1",
        ),
        (
            "MODEL (\n  name: old_model,\n  kind: FULL\n);\nSELECT 1",
            "new_model",
            "MODEL (\n  name: new_model,\n  kind: FULL\n);\nSELECT 1",
        ),
        (
            "MODEL (\n  name target_model\n);\nSELECT 1",
            "target_model",
            "MODEL (\n  name target_model\n);\nSELECT 1",
        ),
        (
            "MODEL (\n  kind FULL\n);\nSELECT 1",
            "new_model",
            "MODEL (\n  name new_model,\n  kind FULL\n);\nSELECT 1",
        ),
        ("SELECT 1 AS id", "new_model", "SELECT 1 AS id"),
        (
            "MODEL (\n  name old_model\nSELECT 1",
            "new_model",
            "MODEL (\n  name old_model\nSELECT 1",
        ),
    ],
)
def test_sync_sqlmesh_model_name(sql: str, new_name: str, expected: str):
    assert sync_sqlmesh_model_name(sql, new_name) == expected


# =============================================================================
# 4. DATAFORM MODEL NAME SYNC TESTS
# =============================================================================


@pytest.mark.parametrize(
    "content,new_name,expected",
    [
        (
            'config {\n  type: "view",\n  name: "old_name"\n}\nSELECT 1',
            "new_name",
            'config {\n  type: "view",\n  name: "new_name"\n}\nSELECT 1',
        ),
        (
            "config {\n  type: 'view',\n  name: 'old_name'\n}\nSELECT 1",
            "new_name",
            "config {\n  type: 'view',\n  name: 'new_name'\n}\nSELECT 1",
        ),
        (
            "config {\n  type: 'view',\n  name: old_name\n}\nSELECT 1",
            "new_name",
            'config {\n  type: \'view\',\n  name: "new_name"\n}\nSELECT 1',
        ),
        (
            'config {\n  name: "current_name"\n}\nSELECT 1',
            "current_name",
            'config {\n  name: "current_name"\n}\nSELECT 1',
        ),
        (
            "config {\n  type: 'view'\n}\nSELECT 1",
            "new_name",
            "config {\n  type: 'view'\n}\nSELECT 1",
        ),
        ("SELECT 1 AS id", "new_name", "SELECT 1 AS id"),
        (
            "config {\n  name: 'old'\nSELECT 1",
            "new_name",
            "config {\n  name: 'old'\nSELECT 1",
        ),
    ],
)
def test_sync_dataform_model_name(content: str, new_name: str, expected: str):
    assert sync_dataform_model_name(content, new_name) == expected


# =============================================================================
# 5. APPLY AUTOFIXES INTEGRATION TESTS
# =============================================================================


def test_apply_autofixes_sqlmesh(tmp_path: Path):
    sql_file = tmp_path / "models" / "orders.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("MODEL (\n  name old_orders\n);\nSELECT 1", encoding="utf-8")

    finding = _make_finding(
        model="old_orders",
        check="filenameequalsmodelname",
        severity="error",
        message="Model name does not match file stem",
        path="models/orders.sql",
    )
    logs = apply_autofixes(
        project_root=tmp_path,
        provider="sqlmesh",
        findings=[finding],
        models={},
    )
    assert len(logs) == 1
    assert "Synchronized model name to 'orders' in orders.sql" in logs[0]
    assert "name orders" in sql_file.read_text(encoding="utf-8")


def test_apply_autofixes_dataform(tmp_path: Path):
    sqlx_file = tmp_path / "definitions" / "users.sqlx"
    sqlx_file.parent.mkdir(parents=True, exist_ok=True)
    sqlx_file.write_text('config {\n  name: "old_users"\n}\nSELECT 1', encoding="utf-8")

    finding = _make_finding(
        model="old_users",
        check="filename_equals_modelname",
        severity="error",
        message="Model name does not match file stem",
        path="definitions/users.sqlx",
    )
    logs = apply_autofixes(
        project_root=tmp_path,
        provider="dataform",
        findings=[finding],
        models={},
    )
    assert len(logs) == 1
    assert "Synchronized model name to 'users' in users.sqlx" in logs[0]
    assert 'name: "users"' in sqlx_file.read_text(encoding="utf-8")


def test_apply_autofixes_ignores_unrelated_findings_and_missing_files(tmp_path: Path):
    # Non-existent file
    missing_finding = _make_finding(
        model="missing",
        check="filenameequalsmodelname",
        severity="error",
        message="Missing",
        path="models/nonexistent.sql",
    )
    # Unfixable rule (e.g. metadata or banselectstar)
    real_file = tmp_path / "models" / "real.sql"
    real_file.parent.mkdir(parents=True, exist_ok=True)
    real_file.write_text("SELECT * FROM t", encoding="utf-8")

    unfixable_finding = _make_finding(
        model="real",
        check="banselectstar",
        severity="error",
        message="SELECT * banned",
        path="models/real.sql",
    )
    no_path_finding = _make_finding(
        model="real",
        check="filenameequalsmodelname",
        severity="error",
        message="No path finding",
        path=None,
    )

    logs = apply_autofixes(
        project_root=tmp_path,
        provider="sqlmesh",
        findings=[missing_finding, unfixable_finding, no_path_finding],
        models={},
    )
    assert logs == []
    # Real file untouched
    assert real_file.read_text(encoding="utf-8") == "SELECT * FROM t"


def test_apply_autofixes_plain_sql_or_already_matching(tmp_path: Path):
    model_file = tmp_path / "models" / "matching.sql"
    model_file.parent.mkdir(parents=True, exist_ok=True)
    model_file.write_text("SELECT 1 AS col", encoding="utf-8")

    finding = _make_finding(
        model="matching",
        check="filenameequalsmodelname",
        severity="error",
        message="Mismatch",
        path="models/matching.sql",
    )
    logs = apply_autofixes(
        project_root=tmp_path,
        provider="dbt",
        findings=[finding],
        models={},
    )
    assert logs == []
    assert model_file.read_text(encoding="utf-8") == "SELECT 1 AS col"


def test_apply_autofixes_handles_write_exceptions(tmp_path: Path):
    sql_file = tmp_path / "models" / "err.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("MODEL (\n  name old_err\n);\nSELECT 1", encoding="utf-8")

    finding = _make_finding(
        model="old_err",
        check="filenameequalsmodelname",
        severity="error",
        message="Mismatch",
        path="models/err.sql",
    )
    with patch("tff.core.autofix.atomic_write", side_effect=OSError("Read-only filesystem")):
        logs = apply_autofixes(
            project_root=tmp_path,
            provider="sqlmesh",
            findings=[finding],
            models={},
        )
    assert len(logs) == 1
    assert "Failed to synchronize model name in err.sql: Read-only filesystem" in logs[0]


def test_apply_autofixes_multi_project_roots(tmp_path: Path):
    r1 = tmp_path / "proj1"
    r2 = tmp_path / "proj2"
    file2 = r2 / "models" / "item.sql"
    file2.parent.mkdir(parents=True, exist_ok=True)
    file2.write_text("MODEL (\n  name old_item\n);\nSELECT 1", encoding="utf-8")

    finding = _make_finding(
        model="old_item",
        check="filenameequalsmodelname",
        severity="error",
        message="Mismatch",
        path="models/item.sql",
    )
    logs = apply_autofixes(
        project_root=[r1, r2],
        provider="sqlmesh",
        findings=[finding],
        models={},
    )
    assert len(logs) == 1
    assert "Synchronized model name to 'item' in item.sql" in logs[0]
    assert "name item" in file2.read_text(encoding="utf-8")
