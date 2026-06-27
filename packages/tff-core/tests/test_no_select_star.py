from pathlib import Path
from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules.no_select_star import NoSelectStar


def test_no_select_star_violations(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.no_select_star.enabled = True
    config.rules.no_select_star.skip_layers = ["sources"]
    config.rules.no_select_star.only_layers = None
    set_ff_config(config)

    rule = NoSelectStar()

    # 1. Violating model in non-skipped layer (marts)
    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM table", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.my_model",
        path=str(sql_file),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation = rule.check_model(model)
    assert violation is not None
    assert "SELECT * is prohibited" in violation.violation_msg[0]

    # 2. Mock model with table-qualified star (a.*) in core layer
    sql_file_qualified = tmp_path / "models/core/my_model.sql"
    sql_file_qualified.parent.mkdir(parents=True, exist_ok=True)
    sql_file_qualified.write_text("SELECT a.*, b.id FROM a JOIN b", encoding="utf-8")

    model_qualified = ModelRepresentation(
        name="core.my_model",
        path=str(sql_file_qualified),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation_qualified = rule.check_model(model_qualified)
    assert violation_qualified is not None

    # 3. Model in skipped layer (sources)
    sql_file_sources = tmp_path / "models/sources/my_model.sql"
    sql_file_sources.parent.mkdir(parents=True, exist_ok=True)
    sql_file_sources.write_text("SELECT * FROM table", encoding="utf-8")

    model_sources = ModelRepresentation(
        name="sources.my_model",
        path=str(sql_file_sources),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation_sources = rule.check_model(model_sources)
    assert violation_sources is None

    # 4. Compliant model (explicit columns) in marts
    sql_file_compliant = tmp_path / "models/marts/compliant_model.sql"
    sql_file_compliant.parent.mkdir(parents=True, exist_ok=True)
    sql_file_compliant.write_text("SELECT col1, col2 FROM table", encoding="utf-8")

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


def test_no_select_star_error_paths(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.no_select_star.enabled = True
    set_ff_config(config)

    rule = NoSelectStar()

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
