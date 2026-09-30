from pathlib import Path
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.rules.no_positional_group_by_or_order_by import (
    NoPositionalGroupByOrOrderBy,
)


def test_no_positional_group_by_or_order_by_violations(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.no_positional_group_by_or_order_by.enabled = True
    config.rules.no_positional_group_by_or_order_by.skip_layers = ["sources"]
    config.rules.no_positional_group_by_or_order_by.only_layers = None

    rule = NoPositionalGroupByOrOrderBy(config=config)

    # 1. Violating GROUP BY in non-skipped layer (marts)
    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT a, b FROM table GROUP BY 1, 2", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.my_model",
        path=str(sql_file),
        dialect="bigquery",
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
        dialect="bigquery",
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
        dialect="bigquery",
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
        dialect="bigquery",
        is_symbolic=False,
    )
    violation_compliant = rule.check_model(model_compliant)
    assert violation_compliant is None

    # 5. Symbolic model
    model_symbolic = ModelRepresentation(
        name="marts.symbolic_model",
        path=str(sql_file_compliant),
        dialect="bigquery",
        is_symbolic=True,
    )
    violation_symbolic = rule.check_model(model_symbolic)
    assert violation_symbolic is None

    # 6. Rule disabled in config
    config.rules.no_positional_group_by_or_order_by.enabled = False
    violation_disabled = rule.check_model(model)
    assert violation_disabled is None


def test_no_positional_group_by_or_order_by_error_paths(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.no_positional_group_by_or_order_by.enabled = True

    rule = NoPositionalGroupByOrOrderBy(config=config)

    # Non-existent file path
    model_missing = ModelRepresentation(
        name="marts.missing",
        path="non_existent_file.sql",
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_missing) is None

    # Invalid SQL syntax
    sql_file = tmp_path / "invalid.sql"
    sql_file.write_text("SELECT * FROM (invalid syntax", encoding="utf-8")
    model_invalid = ModelRepresentation(
        name="marts.invalid",
        path=str(sql_file),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_invalid) is None


def test_no_positional_group_by_or_order_by_individual_toggles(tmp_path: Path):
    sql_file = tmp_path / "models/marts/mixed.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT a, b FROM table GROUP BY 1, 2 ORDER BY 1 DESC", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.mixed",
        path=str(sql_file),
        dialect="bigquery",
        is_symbolic=False,
    )

    # 1. Disable group_by, keep order_by enabled
    config1 = FitnessFunctionsConfig()
    config1.rules.no_positional_group_by_or_order_by.group_by = False
    config1.rules.no_positional_group_by_or_order_by.order_by = True
    rule1 = NoPositionalGroupByOrOrderBy(config=config1)
    v1 = rule1.check_model(model)
    assert v1 is not None
    assert len(v1.violation_msg) == 1
    assert "1 positional ORDER BY reference found" in v1.violation_msg[0]

    # 2. Disable order_by, keep group_by enabled
    config2 = FitnessFunctionsConfig()
    config2.rules.no_positional_group_by_or_order_by.group_by = True
    config2.rules.no_positional_group_by_or_order_by.order_by = False
    rule2 = NoPositionalGroupByOrOrderBy(config=config2)
    v2 = rule2.check_model(model)
    assert v2 is not None
    assert len(v2.violation_msg) == 1
    assert "2 positional GROUP BY references found" in v2.violation_msg[0]

    # 3. Disable both
    config3 = FitnessFunctionsConfig()
    config3.rules.no_positional_group_by_or_order_by.group_by = False
    config3.rules.no_positional_group_by_or_order_by.order_by = False
    rule3 = NoPositionalGroupByOrOrderBy(config=config3)
    v3 = rule3.check_model(model)
    assert v3 is None


def test_no_positional_group_by_rule(tmp_path: Path):
    from tff.core.rules.no_positional_group_by import NoPositionalGroupBy

    config = FitnessFunctionsConfig()
    rule = NoPositionalGroupBy(config=config)

    # Violating GROUP BY
    sql_group = tmp_path / "models/marts/group.sql"
    sql_group.parent.mkdir(parents=True, exist_ok=True)
    sql_group.write_text("SELECT a, b FROM table GROUP BY 1, 2", encoding="utf-8")
    model_group = ModelRepresentation(
        name="marts.group",
        path=str(sql_group),
        dialect="bigquery",
        is_symbolic=False,
    )
    v_group = rule.check_model(model_group)
    assert v_group is not None
    assert "2 positional GROUP BY references found" in v_group.violation_msg[0]

    # Single violation singular suffix
    sql_single = tmp_path / "models/marts/single_group.sql"
    sql_single.write_text("SELECT a FROM table GROUP BY 1", encoding="utf-8")
    model_single = ModelRepresentation(
        name="marts.single_group",
        path=str(sql_single),
        dialect="bigquery",
        is_symbolic=False,
    )
    v_single = rule.check_model(model_single)
    assert v_single is not None
    assert "1 positional GROUP BY reference found" in v_single.violation_msg[0]

    # ORDER BY only should NOT be flagged
    sql_order = tmp_path / "models/marts/order.sql"
    sql_order.write_text("SELECT a, b FROM table ORDER BY 1 DESC", encoding="utf-8")
    model_order = ModelRepresentation(
        name="marts.order",
        path=str(sql_order),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_order) is None

    # Disabled via rule config
    config.rules.no_positional_group_by.enabled = False
    assert rule.check_model(model_group) is None

    # Disabled via parent config group_by toggle
    config.rules.no_positional_group_by.enabled = True
    config.rules.no_positional_group_by_or_order_by.group_by = False
    assert rule.check_model(model_group) is None

    # Disabled via parent config overall enabled
    config.rules.no_positional_group_by_or_order_by.group_by = True
    config.rules.no_positional_group_by_or_order_by.enabled = False
    assert rule.check_model(model_group) is None

    # Re-enable
    config.rules.no_positional_group_by_or_order_by.enabled = True

    # Skipped layer
    sql_sources = tmp_path / "models/sources/group.sql"
    sql_sources.parent.mkdir(parents=True, exist_ok=True)
    sql_sources.write_text("SELECT a FROM table GROUP BY 1", encoding="utf-8")
    model_sources = ModelRepresentation(
        name="sources.group",
        path=str(sql_sources),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_sources) is None

    # Symbolic model
    model_sym = ModelRepresentation(
        name="marts.sym",
        path=str(sql_group),
        dialect="bigquery",
        is_symbolic=True,
    )
    assert rule.check_model(model_sym) is None

    # Missing file / invalid AST
    model_missing = ModelRepresentation(
        name="marts.missing",
        path="non_existent.sql",
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_missing) is None


def test_no_positional_order_by_rule(tmp_path: Path):
    from tff.core.rules.no_positional_order_by import NoPositionalOrderBy

    config = FitnessFunctionsConfig()
    rule = NoPositionalOrderBy(config=config)

    # Violating ORDER BY
    sql_order = tmp_path / "models/marts/order.sql"
    sql_order.parent.mkdir(parents=True, exist_ok=True)
    sql_order.write_text("SELECT a, b FROM table ORDER BY 1, 2 DESC", encoding="utf-8")
    model_order = ModelRepresentation(
        name="marts.order",
        path=str(sql_order),
        dialect="bigquery",
        is_symbolic=False,
    )
    v_order = rule.check_model(model_order)
    assert v_order is not None
    assert "2 positional ORDER BY references found" in v_order.violation_msg[0]

    # Single violation singular suffix
    sql_single = tmp_path / "models/marts/single_order.sql"
    sql_single.write_text("SELECT a FROM table ORDER BY 1", encoding="utf-8")
    model_single = ModelRepresentation(
        name="marts.single_order",
        path=str(sql_single),
        dialect="bigquery",
        is_symbolic=False,
    )
    v_single = rule.check_model(model_single)
    assert v_single is not None
    assert "1 positional ORDER BY reference found" in v_single.violation_msg[0]

    # GROUP BY only should NOT be flagged
    sql_group = tmp_path / "models/marts/group.sql"
    sql_group.write_text("SELECT a, b FROM table GROUP BY 1, 2", encoding="utf-8")
    model_group = ModelRepresentation(
        name="marts.group",
        path=str(sql_group),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_group) is None

    # Disabled via rule config
    config.rules.no_positional_order_by.enabled = False
    assert rule.check_model(model_order) is None

    # Disabled via parent config order_by toggle
    config.rules.no_positional_order_by.enabled = True
    config.rules.no_positional_group_by_or_order_by.order_by = False
    assert rule.check_model(model_order) is None

    # Disabled via parent config overall enabled
    config.rules.no_positional_group_by_or_order_by.order_by = True
    config.rules.no_positional_group_by_or_order_by.enabled = False
    assert rule.check_model(model_order) is None

    # Re-enable
    config.rules.no_positional_group_by_or_order_by.enabled = True

    # Skipped layer
    sql_sources = tmp_path / "models/sources/order.sql"
    sql_sources.parent.mkdir(parents=True, exist_ok=True)
    sql_sources.write_text("SELECT a FROM table ORDER BY 1", encoding="utf-8")
    model_sources = ModelRepresentation(
        name="sources.order",
        path=str(sql_sources),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_sources) is None

    # Symbolic model
    model_sym = ModelRepresentation(
        name="marts.sym",
        path=str(sql_order),
        dialect="bigquery",
        is_symbolic=True,
    )
    assert rule.check_model(model_sym) is None

    # Missing file / invalid AST
    model_missing = ModelRepresentation(
        name="marts.missing",
        path="non_existent.sql",
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_missing) is None

