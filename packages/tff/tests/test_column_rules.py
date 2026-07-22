from tff.core.config import ColumnTypeRuleEntry, FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules.column_names import ColumnNames
from tff.core.rules.column_types import ColumnTypes


def test_column_names_multiple_replacements():
    config = FitnessFunctionsConfig()
    config.rules.column_names.enabled = True
    config.rules.column_names.replacements = {
        "api_request": "api_call",
        "user_dt": "user_date",
    }
    set_ff_config(config)

    model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        columns_to_types={
            "api_request": "varchar",
            "user_dt": "timestamp",
            "other_col": "int",
        },
        is_symbolic=False,
    )

    rule = ColumnNames()
    violation = rule.check_model(model)

    assert violation is not None
    violations_msgs = violation.violation_msg
    assert len(violations_msgs) == 2
    assert "Try changing 'api_request' to 'api_call'." in violations_msgs
    assert "Try changing 'user_dt' to 'user_date'." in violations_msgs


def test_column_types_multiple_rules():
    config = FitnessFunctionsConfig()
    config.rules.column_types.enabled = True
    config.rules.column_types.rules = [
        ColumnTypeRuleEntry(name="id_is_text", pattern="_id$", data_type="text"),
        ColumnTypeRuleEntry(name="date_is_date", pattern="_date$", data_type="date"),
    ]
    set_ff_config(config)

    model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        columns_to_types={
            "user_id": "int",  # should be text
            "created_date": "varchar",  # should be date
            "other_col": "int",
        },
        is_symbolic=False,
    )

    rule = ColumnTypes()
    violation = rule.check_model(model)

    assert violation is not None
    violations_msgs = violation.violation_msg
    assert len(violations_msgs) == 2
    assert any("user_id" in msg and "id_is_text" in msg for msg in violations_msgs)
    assert any(
        "created_date" in msg and "date_is_date" in msg for msg in violations_msgs
    )
