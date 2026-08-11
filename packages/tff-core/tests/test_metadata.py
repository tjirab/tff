from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules.metadata import (
    NoMissingOwner,
    NoMissingDescription,
    NoMissingGrain,
    NoMissingNotNull,
    NoMissingUniqueValues,
)


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


def test_no_missing_owner_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.owner = True
    set_ff_config(config)

    rule = NoMissingOwner()

    # Model with no owner
    model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with owner
    model_with_owner = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        owner="data-team",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_owner) is None

    # Disabled
    config.rules.metadata.owner = False
    set_ff_config(config)
    assert rule.check_model(model) is None


def test_no_missing_description_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.description = True
    set_ff_config(config)

    rule = NoMissingDescription()

    # Model with no description
    model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with description
    model_with_desc = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        description="A great model",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_desc) is None

    # Disabled
    config.rules.metadata.description = False
    set_ff_config(config)
    assert rule.check_model(model) is None


def test_no_missing_grain_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.grain = True
    set_ff_config(config)

    rule = NoMissingGrain()

    # Model with no grain
    model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        grains=[],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with grain
    model_with_grain = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        grains=["user_id"],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_grain) is None

    # Disabled
    config.rules.metadata.grain = False
    set_ff_config(config)
    assert rule.check_model(model) is None


def test_rules_skip_symbolic_and_external_models():
    config = FitnessFunctionsConfig()
    config.rules.metadata.owner = True
    config.rules.metadata.description = True
    config.rules.metadata.grain = True
    config.rules.metadata.not_null = True
    config.rules.metadata.unique_values = True
    set_ff_config(config)

    rules = [
        NoMissingOwner(),
        NoMissingDescription(),
        NoMissingGrain(),
        NoMissingNotNull(),
        NoMissingUniqueValues(),
    ]

    # Symbolic model
    symbolic_model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=True,
        is_external=False,
    )
    for rule in rules:
        assert rule.check_model(symbolic_model) is None

    # External model
    external_model = ModelRepresentation(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=False,
        is_external=True,
    )
    for rule in rules:
        assert rule.check_model(external_model) is None

