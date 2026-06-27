from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules.metadata import NoMissingNotNull, NoMissingUniqueValues


def test_no_missing_not_null_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.not_null = True
    set_ff_config(config)

    rule = NoMissingNotNull()

    # Model with no audits
    model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with not_null audit
    model_with_audit = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[("not_null", {})],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_audit) is None

    # Model with rule disabled in config
    config.rules.metadata.not_null = False
    set_ff_config(config)
    assert rule.check_model(model) is None


def test_no_missing_unique_values_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.unique_values = True
    set_ff_config(config)

    rule = NoMissingUniqueValues()

    # Model with no audits
    model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with unique_values audit
    model_with_audit = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[("unique_values", {})],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_audit) is None

    # Model with rule disabled in config
    config.rules.metadata.unique_values = False
    set_ff_config(config)
    assert rule.check_model(model) is None


def test_rules_skip_symbolic_and_external_models():
    config = FitnessFunctionsConfig()
    config.rules.metadata.not_null = True
    config.rules.metadata.unique_values = True
    set_ff_config(config)

    rule_not_null = NoMissingNotNull()
    rule_unique = NoMissingUniqueValues()

    # Symbolic model
    symbolic_model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=True,
        is_external=False,
    )
    assert rule_not_null.check_model(symbolic_model) is None
    assert rule_unique.check_model(symbolic_model) is None

    # External model
    external_model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=False,
        is_external=True,
    )
    assert rule_not_null.check_model(external_model) is None
    assert rule_unique.check_model(external_model) is None
