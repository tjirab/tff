import pytest
from conftest import _make_model
from tff.core.config import ColumnTypeRuleEntry, FitnessFunctionsConfig
from tff.core.rules.column_names import ColumnNames
from tff.core.rules.column_types import ColumnTypes


@pytest.mark.parametrize(
    ("replacements", "columns", "expected_suggestions"),
    [
        (
            {"api_request": "api_call", "user_dt": "user_date"},
            {"api_request": "varchar", "user_dt": "timestamp", "other_col": "int"},
            ["Try changing 'api_request' to 'api_call'.", "Try changing 'user_dt' to 'user_date'."],
        ),
        (
            {r"^cust_": "customer_", r"_num$": "_count"},
            {"cust_id": "varchar", "order_num": "int", "other_col": "int"},
            ["Try changing 'cust_id' to 'customer_id'.", "Try changing 'order_num' to 'order_count'."],
        ),
    ],
)
def test_column_names_replacements(
    replacements: dict[str, str], columns: dict[str, str], expected_suggestions: list[str]
) -> None:
    config = FitnessFunctionsConfig()
    config.rules.column_names.enabled = True
    config.rules.column_names.replacements = replacements

    model = _make_model(columns_to_types=columns, dialect="bigquery")
    rule = ColumnNames(config=config)
    violation = rule.check_model(model)

    assert violation is not None
    assert len(violation.violation_msg) == len(expected_suggestions)
    for suggestion in expected_suggestions:
        assert suggestion in violation.violation_msg


def test_column_types_multiple_rules() -> None:
    config = FitnessFunctionsConfig()
    config.rules.column_types.enabled = True
    config.rules.column_types.rules = [
        ColumnTypeRuleEntry(name="id_is_text", pattern="_id$", data_type="text"),
        ColumnTypeRuleEntry(name="date_is_date", pattern="_date$", data_type="date"),
    ]

    model = _make_model(
        columns_to_types={
            "user_id": "int",  # should be text
            "created_date": "varchar",  # should be date
            "other_col": "int",
        },
        dialect="bigquery",
    )

    rule = ColumnTypes(config=config)
    violation = rule.check_model(model)

    assert violation is not None
    assert len(violation.violation_msg) == 2
    assert any("user_id" in msg and "id_is_text" in msg for msg in violation.violation_msg)
    assert any("created_date" in msg and "date_is_date" in msg for msg in violation.violation_msg)
