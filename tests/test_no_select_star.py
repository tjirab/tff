from unittest.mock import MagicMock

from sqlglot import parse_one

from sqlmesh_ff.config import FitnessFunctionsConfig
from sqlmesh_ff.context import set_ff_config
from sqlmesh_ff.rules.no_select_star import NoSelectStar


def test_no_select_star_violations():
    config = FitnessFunctionsConfig()
    config.rules.no_select_star.enabled = True
    config.rules.no_select_star.skip_layers = ["sources"]
    config.rules.no_select_star.only_layers = None
    set_ff_config(config)

    # 1. Violating model in non-skipped layer (marts)
    mock_model = MagicMock()
    mock_model._path = "models/marts/my_model.sql"
    mock_model.query = parse_one("SELECT * FROM table")
    mock_model.kind.is_symbolic = False

    rule = NoSelectStar(context=MagicMock())
    violation = rule.check_model(mock_model)
    assert violation is not None
    assert "SELECT * is prohibited" in violation.violation_msg[0]

    # 2. Mock model with table-qualified star (a.*) in core layer
    mock_model_qualified = MagicMock()
    mock_model_qualified._path = "models/core/my_model.sql"
    mock_model_qualified.query = parse_one("SELECT a.*, b.id FROM a JOIN b")
    mock_model_qualified.kind.is_symbolic = False

    violation_qualified = rule.check_model(mock_model_qualified)
    assert violation_qualified is not None

    # 3. Model in skipped layer (sources)
    mock_model_sources = MagicMock()
    mock_model_sources._path = "models/sources/my_model.sql"
    mock_model_sources.query = parse_one("SELECT * FROM table")
    mock_model_sources.kind.is_symbolic = False

    violation_sources = rule.check_model(mock_model_sources)
    assert violation_sources is None

    # 4. Compliant model (explicit columns) in marts
    mock_model_compliant = MagicMock()
    mock_model_compliant._path = "models/marts/my_model.sql"
    mock_model_compliant.query = parse_one("SELECT col1, col2 FROM table")
    mock_model_compliant.kind.is_symbolic = False

    violation_compliant = rule.check_model(mock_model_compliant)
    assert violation_compliant is None

    # 5. Symbolic model or model without query
    mock_model_symbolic = MagicMock()
    mock_model_symbolic._path = "models/marts/my_model.sql"
    mock_model_symbolic.query = None
    mock_model_symbolic.kind.is_symbolic = True

    violation_symbolic = rule.check_model(mock_model_symbolic)
    assert violation_symbolic is None
