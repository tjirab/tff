from unittest.mock import MagicMock

from sqlglot import parse_one

from sqlmesh_ff.config import FitnessFunctionsConfig
from sqlmesh_ff.context import set_ff_config
from sqlmesh_ff.rules.no_positional_group_by_or_order_by import (
    NoPositionalGroupByOrOrderBy,
)


def test_no_positional_group_by_or_order_by_violations():
    config = FitnessFunctionsConfig()
    config.rules.no_positional_group_by_or_order_by.enabled = True
    config.rules.no_positional_group_by_or_order_by.skip_layers = ["sources"]
    config.rules.no_positional_group_by_or_order_by.only_layers = None
    set_ff_config(config)

    rule = NoPositionalGroupByOrOrderBy(context=MagicMock())

    # 1. Violating GROUP BY in non-skipped layer (marts)
    mock_model = MagicMock()
    mock_model._path = "models/marts/my_model.sql"
    mock_model.query = parse_one("SELECT a, b FROM table GROUP BY 1, 2")
    mock_model.kind.is_symbolic = False

    violation = rule.check_model(mock_model)
    assert violation is not None
    assert len(violation.violation_msg) == 1
    assert "2 positional GROUP BY references found. Use column name instead." in violation.violation_msg[0]

    # 2. Violating ORDER BY in core layer
    mock_model_order = MagicMock()
    mock_model_order._path = "models/core/my_model.sql"
    mock_model_order.query = parse_one("SELECT a, b FROM table ORDER BY 1 DESC, b ASC")
    mock_model_order.kind.is_symbolic = False

    violation_order = rule.check_model(mock_model_order)
    assert violation_order is not None
    assert len(violation_order.violation_msg) == 1
    assert "1 positional ORDER BY reference found. Use column name instead." in violation_order.violation_msg[0]

    # 3. Model in skipped layer (sources)
    mock_model_sources = MagicMock()
    mock_model_sources._path = "models/sources/my_model.sql"
    mock_model_sources.query = parse_one("SELECT a, b FROM table GROUP BY 1, 2 ORDER BY 1 DESC")
    mock_model_sources.kind.is_symbolic = False

    violation_sources = rule.check_model(mock_model_sources)
    assert violation_sources is None

    # 4. Compliant model (explicit columns/names) in marts
    mock_model_compliant = MagicMock()
    mock_model_compliant._path = "models/marts/my_model.sql"
    mock_model_compliant.query = parse_one(
        "SELECT col1, col2 FROM table GROUP BY col1, col2 ORDER BY col1 DESC, col2 ASC"
    )
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

    # 6. Rule disabled in config
    config.rules.no_positional_group_by_or_order_by.enabled = False
    set_ff_config(config)
    violation_disabled = rule.check_model(mock_model)
    assert violation_disabled is None
