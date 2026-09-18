"""Tests for tff-core structured exception hierarchy and OS error translation."""

import errno
from pathlib import Path
from unittest.mock import patch
import pytest

from tff.core.config import FitnessFunctionsConfig, load_fitness_config, resolve_project_path
from tff.core.exceptions import (
    TffConfigError,
    TffError,
    TffFileError,
    TffManifestError,
    TffManifestNotFoundError,
    TffModelError,
    handle_os_errors,
    normalize_os_error,
    translate_os_error,
)
from tff.core.model import ModelRepresentation, read_file_safe, read_model_sql
from tff.dataform.manifest import _find_manifest_file, load_dataform_models
from tff.dbt.manifest import load_dbt_models


def test_tff_error_base():
    err = TffError("Something went wrong", hint="Do this to fix it", details={"k": "v"})
    assert err.message == "Something went wrong"
    assert err.hint == "Do this to fix it"
    assert err.details == {"k": "v"}
    assert "Something went wrong" in str(err)
    assert "Hint: Do this to fix it" in str(err)
    assert isinstance(err, Exception)

    err_no_hint = TffError("Plain error")
    assert str(err_no_hint) == "Plain error"
    assert err_no_hint.hint is None
    assert err_no_hint.details == {}


def test_tff_file_error():
    path = Path("/path/to/file.sql")
    err = TffFileError(
        "Cannot open file",
        hint="Check permissions",
        path=path,
        operation="read",
        details={"extra": 123},
    )
    assert isinstance(err, TffError)
    assert isinstance(err, OSError)
    assert err.path == path
    assert err.operation == "read"
    assert err.details["path"] == str(path)
    assert err.details["operation"] == "read"
    assert err.details["extra"] == 123
    assert "Hint: Check permissions" in str(err)


def test_tff_model_error():
    path = Path("/path/to/my_model.sql")
    err = TffModelError(
        "Failed to resolve model",
        hint="Check model definition",
        model_name="my_model",
        path=path,
    )
    assert isinstance(err, TffError)
    assert not isinstance(err, OSError)
    assert err.model_name == "my_model"
    assert err.path == path
    assert err.details["model_name"] == "my_model"
    assert err.details["path"] == str(path)


def test_tff_config_error():
    path = Path("fitness_functions.yaml")
    err = TffConfigError(
        "Invalid config YAML",
        hint="Check indentation",
        path=path,
    )
    assert isinstance(err, TffError)
    assert isinstance(err, ValueError)
    assert err.path == path
    assert err.details["path"] == str(path)


def test_tff_manifest_error():
    path = Path("target/manifest.json")
    err = TffManifestError(
        "Corrupt manifest",
        hint="Recompile dbt project",
        provider="dbt",
        path=path,
    )
    assert isinstance(err, TffError)
    assert isinstance(err, OSError)
    assert err.provider == "dbt"
    assert err.path == path
    assert err.details["provider"] == "dbt"
    assert err.details["path"] == str(path)


def test_tff_manifest_not_found_error():
    path = Path("target/manifest.json")
    err = TffManifestNotFoundError(
        "Manifest not found",
        hint="Run dbt compile",
        provider="dbt",
        path=path,
    )
    assert isinstance(err, TffManifestError)
    assert isinstance(err, FileNotFoundError)
    assert isinstance(err, OSError)
    assert isinstance(err, TffError)


def test_normalize_os_error_eisdir():
    raw_exc = IsADirectoryError(errno.EISDIR, "Is a directory", "/test/dir")
    normalized = normalize_os_error(raw_exc, path="/test/dir", expected_type="SQL file")

    assert isinstance(normalized, TffFileError)
    assert normalized.details["errno"] == errno.EISDIR
    assert "Expected a SQL file, but encountered a directory: '/test/dir'" in normalized.message
    assert "Ensure the path '/test/dir' points to a valid file, not a directory." in normalized.hint


def test_normalize_os_error_eisdir_with_model_name():
    raw_exc = IsADirectoryError(errno.EISDIR, "Is a directory", "/test/models/customers")
    normalized = normalize_os_error(
        raw_exc,
        path="/test/models/customers",
        model_name="customers",
        expected_type="SQL file",
    )

    assert isinstance(normalized, TffModelError)
    assert normalized.model_name == "customers"
    assert normalized.details["model_name"] == "customers"
    assert "Expected a SQL file, but encountered a directory" in normalized.message


def test_normalize_os_error_enoent():
    raw_exc = FileNotFoundError(errno.ENOENT, "No such file", "/test/missing.sql")
    normalized = normalize_os_error(raw_exc, path="/test/missing.sql", expected_type="SQL file")

    assert isinstance(normalized, TffFileError)
    assert "No such SQL file: '/test/missing.sql'" in normalized.message
    assert "Verify that the file exists" in normalized.hint


def test_normalize_os_error_enoent_manifest():
    raw_exc = FileNotFoundError(errno.ENOENT, "No such file", "/test/target/manifest.json")
    normalized = normalize_os_error(
        raw_exc,
        path="/test/target/manifest.json",
        expected_type="dbt manifest file",
        provider="dbt",
    )

    assert isinstance(normalized, TffManifestNotFoundError)
    assert isinstance(normalized, FileNotFoundError)
    assert normalized.provider == "dbt"
    assert "No such dbt manifest file" in normalized.message


def test_normalize_os_error_eacces():
    raw_exc = PermissionError(errno.EACCES, "Permission denied", "/test/secret.sql")
    normalized = normalize_os_error(
        raw_exc,
        path="/test/secret.sql",
        operation="read",
        expected_type="SQL file",
    )

    assert isinstance(normalized, TffFileError)
    assert "Permission denied while attempting to read SQL file: '/test/secret.sql'" in normalized.message
    assert "Check filesystem permissions" in normalized.hint


def test_normalize_os_error_enotdir():
    raw_exc = NotADirectoryError(errno.ENOTDIR, "Not a directory", "/test/file.sql/sub")
    normalized = normalize_os_error(raw_exc, path="/test/file.sql/sub")

    assert isinstance(normalized, TffFileError)
    assert "A component of the path prefix is not a directory" in normalized.message


def test_normalize_os_error_emfile():
    raw_exc = OSError(errno.EMFILE, "Too many open files", "/test/file.sql")
    normalized = normalize_os_error(raw_exc, path="/test/file.sql")

    assert isinstance(normalized, TffFileError)
    assert "Too many open files" in normalized.message
    assert "Consider reducing concurrency" in normalized.hint


def test_normalize_os_error_generic_and_unknown_path():
    raw_exc = OSError(errno.EIO, "I/O error")
    normalized = normalize_os_error(raw_exc)

    assert isinstance(normalized, TffFileError)
    assert "Failed to read file '<unknown path>'" in normalized.message
    assert normalized.path is None
    assert normalized.details.get("path") is None


def test_normalize_os_error_already_tff_error():
    original = TffFileError("Existing domain error")
    result = normalize_os_error(original)
    assert result is original


def test_normalize_os_error_custom_hint_and_details():
    raw_exc = IsADirectoryError(errno.EISDIR, "Is a directory")
    normalized = normalize_os_error(
        raw_exc,
        path="/some/dir",
        hint="Custom resolution step",
        details={"user_ctx": "test_run"},
    )
    assert normalized.hint == "Custom resolution step"
    assert normalized.details["user_ctx"] == "test_run"


def test_translate_os_error_alias():
    raw_exc = IsADirectoryError(errno.EISDIR, "Is a directory")
    normalized = translate_os_error(raw_exc, path="/some/dir")
    assert isinstance(normalized, TffFileError)


def test_handle_os_errors_context_manager():
    with handle_os_errors(path="/tmp/test", operation="read"):
        pass  # no error raised

    with pytest.raises(TffFileError) as exc_info:
        with handle_os_errors(path="/tmp/nonexistent", operation="read", expected_type="SQL file"):
            raise FileNotFoundError(errno.ENOENT, "No such file", "/tmp/nonexistent")

    assert "No such SQL file: '/tmp/nonexistent'" in exc_info.value.message

    # Non-OS errors are unaffected
    with pytest.raises(KeyError):
        with handle_os_errors(path="/tmp/test"):
            raise KeyError("not an os error")


def test_read_file_safe_with_raise_on_error(tmp_path: Path):
    # Valid file
    f = tmp_path / "valid.sql"
    f.write_text("SELECT 1;", encoding="utf-8")
    assert read_file_safe(f, raise_on_error=True) == "SELECT 1;"

    # None or empty path
    with pytest.raises(TffFileError, match="No file path was provided"):
        read_file_safe(None, raise_on_error=True)

    # Directory
    d = tmp_path / "sub_dir"
    d.mkdir()
    with pytest.raises(TffFileError) as exc_info:
        read_file_safe(d, raise_on_error=True, expected_type="SQL file")
    assert "Expected a SQL file, but encountered a directory" in exc_info.value.message

    # Missing file
    missing = tmp_path / "does_not_exist.sql"
    with pytest.raises(TffFileError) as exc_info:
        read_file_safe(missing, raise_on_error=True, expected_type="SQL file")
    assert "No such SQL file" in exc_info.value.message

    # When model_name is provided, raises TffModelError
    with pytest.raises(TffModelError) as exc_info:
        read_file_safe(missing, raise_on_error=True, model_name="orders")
    assert exc_info.value.model_name == "orders"

    # Path read_text raises OSError
    with patch.object(Path, "read_text", side_effect=OSError("Disk read failure")):
        with pytest.raises(TffFileError) as exc_info:
            read_file_safe(f, raise_on_error=True)
        assert "Failed to read file" in exc_info.value.message



def test_read_model_sql_with_raise_on_error(tmp_path: Path):
    # Model with query attribute
    m_query = ModelRepresentation(name="m1", path="", dialect="postgres", query="SELECT 1")
    assert read_model_sql(m_query, raise_on_error=True) == "SELECT 1"

    # Model with unreadable file and no query
    d = tmp_path / "model_dir"
    d.mkdir()
    m_dir = ModelRepresentation(name="m_dir", path=str(d), dialect="postgres")
    with pytest.raises(TffModelError) as exc_info:
        read_model_sql(m_dir, raise_on_error=True)
    assert exc_info.value.model_name == "m_dir"
    assert "Expected a SQL file, but encountered a directory" in exc_info.value.message

    # ModelRepresentation get_sql and read_sql raise_on_error pass-through
    with pytest.raises(TffModelError):
        m_dir.get_sql(raise_on_error=True)
    with pytest.raises(TffModelError):
        m_dir.read_sql(raise_on_error=True)

    # prefer_file=True fallback with raise_on_error
    m_pref = ModelRepresentation(name="m_pref", path=str(tmp_path / "missing.sql"), dialect="postgres")
    with pytest.raises(TffModelError):
        m_pref.get_sql(prefer_file=True, raise_on_error=True)


def test_dbt_manifest_loader_exceptions(tmp_path: Path):
    # Missing manifest raises TffManifestNotFoundError
    with pytest.raises(TffManifestNotFoundError) as exc_info:
        load_dbt_models(tmp_path)
    assert exc_info.value.provider == "dbt"
    assert isinstance(exc_info.value, FileNotFoundError)

    # Manifest path is a directory raises TffManifestError with EISDIR
    target = tmp_path / "target"
    target.mkdir()
    manifest_dir = target / "manifest.json"
    manifest_dir.mkdir()
    with pytest.raises(TffManifestError) as exc_info:
        load_dbt_models(tmp_path)
    assert "Expected a dbt manifest file, but encountered a directory" in exc_info.value.message

    # Manifest path is corrupt JSON raises TffManifestError
    manifest_dir.rmdir()
    manifest_dir.write_text("invalid json {", encoding="utf-8")
    with pytest.raises(TffManifestError) as exc_info:
        load_dbt_models(tmp_path)
    assert "Failed to parse dbt manifest" in exc_info.value.message

    # Manifest file open raises OSError
    m_file = target / "manifest.json"
    m_file.write_text("{}", encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("Cannot read manifest")):
        with pytest.raises(TffManifestError) as exc_info:
            load_dbt_models(tmp_path)
        assert "Permission denied while attempting to read dbt manifest file" in exc_info.value.message


def test_dataform_manifest_loader_exceptions(tmp_path: Path):
    # Non-existent specified manifest raises TffManifestNotFoundError
    with pytest.raises(TffManifestNotFoundError) as exc_info:
        _find_manifest_file(tmp_path, "missing.json")
    assert exc_info.value.provider == "dataform"
    assert isinstance(exc_info.value, FileNotFoundError)

    # Manifest path is a directory raises TffManifestError (EISDIR)
    dir_manifest = tmp_path / "manifest_dir"
    dir_manifest.mkdir()
    with pytest.raises(TffManifestError) as exc_info:
        _find_manifest_file(tmp_path, dir_manifest)
    assert "Expected a Dataform manifest file, but encountered a directory" in exc_info.value.message

    # Corrupt manifest file passed to load_dataform_models raises TffManifestError
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text("not json", encoding="utf-8")
    with pytest.raises(TffManifestError) as exc_info:
        load_dataform_models(tmp_path, manifest_path=bad_manifest)
    assert "Failed to parse Dataform manifest" in exc_info.value.message

    # Dataform manifest open raises OSError
    df_manifest = tmp_path / "df_manifest.json"
    df_manifest.write_text("{}", encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("Cannot read dataform manifest")):
        with pytest.raises(TffManifestError) as exc_info:
            load_dataform_models(tmp_path, manifest_path=df_manifest)
        assert "Permission denied while attempting to read Dataform manifest file" in exc_info.value.message

    # Dataform manifest raises TffError in load_dataform_models
    with patch("tff.dataform.manifest._parse_compiled_graph", side_effect=TffManifestError("Graph error")):
        with pytest.raises(TffManifestError, match="Graph error"):
            load_dataform_models(tmp_path, manifest_path=df_manifest)


def test_config_loader_exceptions(tmp_path: Path):
    # Directory where config file is expected raises TffFileError
    cfg_dir = tmp_path / "fitness_functions.yaml"
    cfg_dir.mkdir()
    with pytest.raises(TffFileError) as exc_info:
        load_fitness_config(tmp_path)
    assert "Expected a configuration file, but encountered a directory" in exc_info.value.message
    cfg_dir.rmdir()

    # Config file exists but read_text raises OSError
    valid_cfg = tmp_path / "valid_cfg"
    valid_cfg.mkdir()
    cfg_file = valid_cfg / "fitness_functions.yaml"
    cfg_file.write_text("health: {}", encoding="utf-8")
    with patch.object(Path, "read_text", side_effect=PermissionError("Permission denied")):
        with pytest.raises(TffFileError) as exc_info:
            load_fitness_config(valid_cfg)
        assert "Permission denied while attempting to read configuration file" in exc_info.value.message

    # Corrupt YAML in config raises TffConfigError
    cfg_file = tmp_path / "fitness_functions.yaml"
    cfg_file.write_text("invalid: yaml: :", encoding="utf-8")
    with pytest.raises(TffConfigError) as exc_info:
        load_fitness_config(tmp_path)
    assert "Failed to parse YAML configuration" in exc_info.value.message

    # Non-mapping YAML in config raises TffConfigError
    cfg_file.write_text("- item1\n- item2\n", encoding="utf-8")
    with pytest.raises(TffConfigError) as exc_info:
        load_fitness_config(tmp_path)
    assert "Expected mapping in" in exc_info.value.message

    # Path resolving outside project root raises TffConfigError (subclass of ValueError)
    cfg = FitnessFunctionsConfig()
    cfg._project_root = tmp_path
    with pytest.raises(TffConfigError) as exc_info:
        resolve_project_path(cfg, "../../outside.json")
    assert isinstance(exc_info.value, ValueError)
    assert "resolves outside project root" in exc_info.value.message
