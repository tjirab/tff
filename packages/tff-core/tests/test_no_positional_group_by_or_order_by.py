from pathlib import Path
from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules.no_positional_group_by_or_order_by import (
    NoPositionalGroupByOrOrderBy,
)


def test_no_positional_group_by_or_order_by_violations(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.no_positional_group_by_or_order_by.enabled = True
    config.rules.no_positional_group_by_or_order_by.skip_layers = ["sources"]
    config.rules.no_positional_group_by_or_order_by.only_layers = None
    set_ff_config(config)

    rule = NoPositionalGroupByOrOrderBy()

    # 1. Violating GROUP BY in non-skipped layer (marts)
    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT a, b FROM table GROUP BY 1, 2", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.my_model",
        path=str(sql_file),
        is_symbolic=False,
    )
    violation = rule.check_model(model)
    assert violation is not None
    assert len(violation.violation_msg) == 1
    assert "2 positional GROUP BY references found. Use column name instead." in violation.violation_msg[0]

    # 2. Violating ORDER BY in core layer
    sql_file_order = tmp_path / "models/core/my_model.sql"
    sql_file_order.parent.mkdir(parents=True, exist_ok=True)
    sql_file_order.write_text("SELECT a, b FROM table ORDER BY 1 DESC, b ASC", encoding="utf-8")

    model_order = ModelRepresentation(
        name="core.my_model",
        path=str(sql_file_order),
        is_symbolic=False,
    )
    violation_order = rule.check_model(model_order)
    assert violation_order is not None
    assert len(violation_order.violation_msg) == 1
    assert "1 positional ORDER BY reference found. Use column name instead." in violation_order.violation_msg[0]

    # 3. Model in skipped layer (sources)
    sql_file_sources = tmp_path / "models/sources/my_model.sql"
    sql_file_sources.parent.mkdir(parents=True, exist_ok=True)
    sql_file_sources.write_text("SELECT a, b FROM table GROUP BY 1, 2 ORDER BY 1 DESC", encoding="utf-8")

    model_sources = ModelRepresentation(
        name="sources.my_model",
        path=str(sql_file_sources),
        is_symbolic=False,
    )
    violation_sources = rule.check_model(model_sources)
    assert violation_sources is None

    # 4. Compliant model (explicit columns/names) in marts
    sql_file_compliant = tmp_path / "models/marts/compliant_model.sql"
    sql_file_compliant.parent.mkdir(parents=True, exist_ok=True)
    sql_file_compliant.write_text("SELECT col1, col2 FROM table GROUP BY col1, col2 ORDER BY col1 DESC, col2 ASC", encoding="utf-8")

    model_compliant = ModelRepresentation(
        name="marts.compliant_model",
        path=str(sql_file_compliant),
        is_symbolic=False,
    )
    violation_compliant = rule.check_model(model_compliant)
    assert violation_compliant is None

    # 5. Symbolic model
    model_symbolic = ModelRepresentation(
        name="marts.symbolic_model",
        path=str(sql_file_compliant),
        is_symbolic=True,
    )
    violation_symbolic = rule.check_model(model_symbolic)
    assert violation_symbolic is None

    # 6. Rule disabled in config
    config.rules.no_positional_group_by_or_order_by.enabled = False
    set_ff_config(config)
    violation_disabled = rule.check_model(model)
    assert violation_disabled is None


def test_no_positional_group_by_or_order_by_error_paths(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.no_positional_group_by_or_order_by.enabled = True
    set_ff_config(config)

    rule = NoPositionalGroupByOrOrderBy()

    # Non-existent file path
    model_missing = ModelRepresentation(
        name="marts.missing",
        path="non_existent_file.sql",
        is_symbolic=False,
    )
    assert rule.check_model(model_missing) is None

    # Invalid SQL syntax
    sql_file = tmp_path / "invalid.sql"
    sql_file.write_text("SELECT * FROM (invalid syntax", encoding="utf-8")
    model_invalid = ModelRepresentation(
        name="marts.invalid",
        path=str(sql_file),
        is_symbolic=False,
    )
    assert rule.check_model(model_invalid) is None
