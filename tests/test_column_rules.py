from unittest.mock import MagicMock

from sqlglot import exp

from sqlmesh_ff.config import ColumnTypeRuleEntry, FitnessFunctionsConfig
from sqlmesh_ff.context import set_ff_config
from sqlmesh_ff.rules.column_names import ColumnNames
from sqlmesh_ff.rules.column_types import ColumnTypes


def test_column_names_multiple_replacements():
    # Configure fitness config with multiple replacements
    config = FitnessFunctionsConfig()
    config.rules.column_names.enabled = True
    config.rules.column_names.replacements = {
        "api_request": "api_call",
        "user_dt": "user_date",
    }
    set_ff_config(config)

    # Mock a model with columns violating multiple replacements
    mock_model = MagicMock()
    mock_model.columns_to_types = {
        "api_request": exp.DataType.build("VARCHAR"),
        "user_dt": exp.DataType.build("TIMESTAMP"),
        "other_col": exp.DataType.build("INT"),
    }
    mock_model.kind.is_symbolic = False

    rule = ColumnNames(context=MagicMock())
    violation = rule.check_model(mock_model)

    assert violation is not None
    violations_msgs = violation.violation_msg
    assert len(violations_msgs) == 2
    assert "Try changing 'api_request' to 'api_call'." in violations_msgs
    assert "Try changing 'user_dt' to 'user_date'." in violations_msgs


def test_column_types_multiple_rules():
    # Configure fitness config with multiple column type rules
    config = FitnessFunctionsConfig()
    config.rules.column_types.enabled = True
    config.rules.column_types.rules = [
        ColumnTypeRuleEntry(name="id_is_text", pattern="_id$", data_type="text"),
        ColumnTypeRuleEntry(name="date_is_date", pattern="_date$", data_type="date"),
    ]
    set_ff_config(config)

    # Mock a model violating both rules
    mock_model = MagicMock()
    mock_model.columns_to_types = {
        "user_id": exp.DataType.build("INT"),  # should be text
        "created_date": exp.DataType.build("VARCHAR"),  # should be date
        "other_col": exp.DataType.build("INT"),
    }
    mock_model.kind.is_symbolic = False

    rule = ColumnTypes(context=MagicMock())
    violation = rule.check_model(mock_model)

    assert violation is not None
    violations_msgs = violation.violation_msg
    assert len(violations_msgs) == 2
    assert any("user_id" in msg and "id_is_text" in msg for msg in violations_msgs)
    assert any(
        "created_date" in msg and "date_is_date" in msg for msg in violations_msgs
    )
