from pathlib import Path
from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules.environment_agnostic_references import EnvironmentAgnosticReferences


def test_environment_agnostic_references_violations(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.environment_agnostic_references.enabled = True
    config.rules.environment_agnostic_references.banned_environments = ["prod", "dev", "staging"]
    set_ff_config(config)

    rule = EnvironmentAgnosticReferences()

    # 1. Banned environment in catalog
    sql_file = tmp_path / "models/marts/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM prod_db.raw_schema.table", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.my_model",
        path=str(sql_file),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation = rule.check_model(model)
    assert violation is not None
    assert "prod_db" in violation.violation_msg[0]

    # 2. Banned environment in schema (dev_raw)
    sql_file_dev = tmp_path / "models/marts/my_model_dev.sql"
    sql_file_dev.write_text("SELECT * FROM dev_raw.table", encoding="utf-8")

    model_dev = ModelRepresentation(
        name="marts.my_model_dev",
        path=str(sql_file_dev),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation_dev = rule.check_model(model_dev)
    assert violation_dev is not None
    assert "dev_raw" in violation_dev.violation_msg[0]

    # 3. Multiple violations in same query
    sql_file_multi = tmp_path / "models/marts/multi.sql"
    sql_file_multi.write_text(
        "SELECT * FROM prod_db.schema.a JOIN dev-db.schema.b ON a.id = b.id", encoding="utf-8"
    )

    model_multi = ModelRepresentation(
        name="marts.multi",
        path=str(sql_file_multi),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation_multi = rule.check_model(model_multi)
    assert violation_multi is not None
    assert len(violation_multi.violation_msg) == 2
    assert "prod_db" in violation_multi.violation_msg[0]
    assert "dev-db" in violation_multi.violation_msg[1]

    # 4. Compliant references (no banned env names)
    sql_file_compliant = tmp_path / "models/marts/compliant.sql"
    sql_file_compliant.write_text("SELECT * FROM schema.table", encoding="utf-8")

    model_compliant = ModelRepresentation(
        name="marts.compliant",
        path=str(sql_file_compliant),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_compliant) is None

    # 5. Single part table references (no schema or catalog prefix)
    sql_file_single = tmp_path / "models/marts/single.sql"
    sql_file_single.write_text("SELECT * FROM table", encoding="utf-8")

    model_single = ModelRepresentation(
        name="marts.single",
        path=str(sql_file_single),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_single) is None

    # 6. Avoid false positives on substrings like 'device' or 'product'
    sql_file_fp = tmp_path / "models/marts/fp.sql"
    sql_file_fp.write_text("SELECT * FROM device_data.table JOIN production.other", encoding="utf-8")

    model_fp = ModelRepresentation(
        name="marts.fp",
        path=str(sql_file_fp),
        dialect="bigquery",
        is_symbolic=False,
    )
    assert rule.check_model(model_fp) is None


def test_jinja_and_macro_handling(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.environment_agnostic_references.enabled = True
    config.rules.environment_agnostic_references.banned_environments = ["prod", "dev"]
    set_ff_config(config)

    rule = EnvironmentAgnosticReferences()

    # 1. dbt ref style (uncompiled raw code)
    sql_file_jinja = tmp_path / "models/marts/jinja.sql"
    sql_file_jinja.parent.mkdir(parents=True, exist_ok=True)
    sql_file_jinja.write_text(
        "SELECT * FROM {{ ref('my_model') }} JOIN prod_db.schema.table", encoding="utf-8"
    )

    model_jinja = ModelRepresentation(
        name="marts.jinja",
        path=str(sql_file_jinja),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation_jinja = rule.check_model(model_jinja)
    assert violation_jinja is not None
    assert len(violation_jinja.violation_msg) == 1
    assert "prod_db" in violation_jinja.violation_msg[0]

    # 2. SQLMesh ref macro style
    sql_file_macro = tmp_path / "models/marts/macro.sql"
    sql_file_macro.parent.mkdir(parents=True, exist_ok=True)
    sql_file_macro.write_text(
        "SELECT * FROM @ref(my_schema.my_model) JOIN dev_db.schema.table", encoding="utf-8"
    )

    model_macro = ModelRepresentation(
        name="marts.macro",
        path=str(sql_file_macro),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation_macro = rule.check_model(model_macro)
    assert violation_macro is not None
    assert len(violation_macro.violation_msg) == 1
    assert "dev_db" in violation_macro.violation_msg[0]


def test_custom_banned_environments(tmp_path: Path):
    config = FitnessFunctionsConfig()
    config.rules.environment_agnostic_references.enabled = True
    config.rules.environment_agnostic_references.banned_environments = ["custom_env"]
    set_ff_config(config)

    rule = EnvironmentAgnosticReferences()

    sql_file = tmp_path / "models/marts/custom.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM custom_env.table JOIN prod.table", encoding="utf-8")

    model = ModelRepresentation(
        name="marts.custom",
        path=str(sql_file),
        dialect="bigquery",
        is_symbolic=False,
    )
    violation = rule.check_model(model)
    assert violation is not None
    assert len(violation.violation_msg) == 1
    assert "custom_env" in violation.violation_msg[0]
    assert "prod.table" not in violation.violation_msg[0]
