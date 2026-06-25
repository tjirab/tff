from unittest.mock import MagicMock

from sqlmesh_ff.config import FitnessFunctionsConfig
from sqlmesh_ff.context import set_ff_config
from sqlmesh_ff.rules.metadata import NoMissingNotNull, NoMissingUniqueValues


def test_no_missing_not_null_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.not_null = True
    set_ff_config(config)

    rule = NoMissingNotNull(context=MagicMock())

    # Mock model with no audits
    mock_model = MagicMock()
    mock_model.audits = []
    mock_model.kind.is_symbolic = False
    mock_model.kind.is_external = False

    assert rule.check_model(mock_model) is not None

    # Mock model with not_null audit
    mock_model_with_audit = MagicMock()
    mock_model_with_audit.audits = [("not_null", {})]
    mock_model_with_audit.kind.is_symbolic = False
    mock_model_with_audit.kind.is_external = False

    assert rule.check_model(mock_model_with_audit) is None

    # Mock model with rule disabled in config
    config.rules.metadata.not_null = False
    set_ff_config(config)
    assert rule.check_model(mock_model) is None


def test_no_missing_unique_values_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.unique_values = True
    set_ff_config(config)

    rule = NoMissingUniqueValues(context=MagicMock())

    # Mock model with no audits
    mock_model = MagicMock()
    mock_model.audits = []
    mock_model.kind.is_symbolic = False
    mock_model.kind.is_external = False

    assert rule.check_model(mock_model) is not None

    # Mock model with unique_values audit
    mock_model_with_audit = MagicMock()
    mock_model_with_audit.audits = [("unique_values", {})]
    mock_model_with_audit.kind.is_symbolic = False
    mock_model_with_audit.kind.is_external = False

    assert rule.check_model(mock_model_with_audit) is None

    # Mock model with rule disabled in config
    config.rules.metadata.unique_values = False
    set_ff_config(config)
    assert rule.check_model(mock_model) is None


def test_rules_skip_symbolic_and_external_models():
    config = FitnessFunctionsConfig()
    config.rules.metadata.not_null = True
    config.rules.metadata.unique_values = True
    set_ff_config(config)

    rule_not_null = NoMissingNotNull(context=MagicMock())
    rule_unique = NoMissingUniqueValues(context=MagicMock())

    # Symbolic model
    symbolic_model = MagicMock()
    symbolic_model.audits = []
    symbolic_model.kind.is_symbolic = True
    symbolic_model.kind.is_external = False

    assert rule_not_null.check_model(symbolic_model) is None
    assert rule_unique.check_model(symbolic_model) is None

    # External model
    external_model = MagicMock()
    external_model.audits = []
    external_model.kind.is_symbolic = False
    external_model.kind.is_external = True

    assert rule_not_null.check_model(external_model) is None
    assert rule_unique.check_model(external_model) is None

