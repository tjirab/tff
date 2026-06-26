import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlmesh.utils.errors import SQLMeshError

from sqlmesh_ff.checks.custom_exclusions import CustomExclusionsChecker


def test_custom_exclusions_checker_handles_sqlmesh_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    exclusions_file = tmp_path / "exclusions.json"
    exclusions_file.write_text("{}", encoding="utf-8")

    # Mock SQLMesh context
    mock_context = MagicMock()
    # get_model raises SQLMeshError
    mock_context.get_model.side_effect = SQLMeshError("Model lookup failed")

    checker = CustomExclusionsChecker(mock_context, exclusions_file)

    # Mock model
    mock_model = MagicMock()
    mock_model.kind.is_symbolic = False
    mock_model._path = "models/core/my_model.sql"
    mock_model.name = "my_model"
    mock_model.depends_on = ["dependency_model"]

    # Run check
    with caplog.at_level(logging.WARNING):
        violations = checker.check_model(mock_model)

    assert violations == []
    # Assert warning was logged
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "WARNING"
    assert "Could not check dependency dependency_model for model my_model" in caplog.records[0].message
    assert "SQLMesh error: Model lookup failed" in caplog.records[0].message


def test_custom_exclusions_checker_handles_unexpected_error(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    exclusions_file = tmp_path / "exclusions.json"
    exclusions_file.write_text("{}", encoding="utf-8")

    # Mock SQLMesh context
    mock_context = MagicMock()
    # get_model raises RuntimeError
    mock_context.get_model.side_effect = RuntimeError("Something went wrong")

    checker = CustomExclusionsChecker(mock_context, exclusions_file)

    # Mock model
    mock_model = MagicMock()
    mock_model.kind.is_symbolic = False
    mock_model._path = "models/core/my_model.sql"
    mock_model.name = "my_model"
    mock_model.depends_on = ["dependency_model"]

    # Run check
    with caplog.at_level(logging.ERROR):
        violations = checker.check_model(mock_model)

    assert violations == []
    # Assert error was logged
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == "ERROR"
    assert "Unexpected error checking dependency dependency_model for model my_model" in caplog.records[0].message
    assert "Something went wrong" in caplog.records[0].message
