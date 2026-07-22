from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules.mart_naming import MartModelNamingConvention


def test_mart_model_naming_convention():
    config = FitnessFunctionsConfig()
    config.rules.mart_naming.enabled = True
    config.rules.mart_naming.layer_name = "marts"
    config.rules.mart_naming.rule = "prefix_with_subdirectory"
    set_ff_config(config)

    rule = MartModelNamingConvention()

    # 1. Mart model violating naming convention
    model_violation = ModelRepresentation(
        name="marts.marketing.all_users",
        path="models/marts/marketing/all_users.sql",
        dialect="bigquery",
        is_symbolic=False,
    )
    violation = rule.check_model(model_violation)
    assert violation is not None
    assert "should start with 'marketing_'" in violation.violation_msg

    # 2. Mart model matching naming convention
    model_ok = ModelRepresentation(
        name="marts.marketing.marketing_all_users",
        path="models/marts/marketing/marketing_all_users.sql",
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_ok) is None

    # 3. Non-mart model (staging) - should be skipped
    model_stg = ModelRepresentation(
        name="staging.stg_users",
        path="models/staging/stg_users.sql",
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_stg) is None
