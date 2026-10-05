import pytest
from conftest import _make_model
from tff.core.config import FitnessFunctionsConfig
from tff.core.rules.mart_naming import MartModelNamingConvention


@pytest.mark.parametrize(
    ("name", "path", "expect_violation"),
    [
        ("marts.marketing.all_users", "models/marts/marketing/all_users.sql", True),
        ("marts.marketing.marketing_all_users", "models/marts/marketing/marketing_all_users.sql", False),
        ("staging.stg_users", "models/staging/stg_users.sql", False),
    ],
)
def test_mart_model_naming_convention(name: str, path: str, expect_violation: bool) -> None:
    config = FitnessFunctionsConfig()
    config.rules.mart_naming.enabled = True
    config.rules.mart_naming.layer_name = "marts"
    config.rules.mart_naming.rule = "prefix_with_subdirectory"

    rule = MartModelNamingConvention(config=config)
    model = _make_model(name=name, path=path, dialect="bigquery")
    violation = rule.check_model(model)

    if expect_violation:
        assert violation is not None
        assert "should start with 'marketing_'" in violation.violation_msg
    else:
        assert violation is None
