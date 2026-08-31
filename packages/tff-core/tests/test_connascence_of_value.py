
from tff.core.checks.connascence_of_value import collect_connascence_of_value_findings
from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation


def test_cov_no_duplicates():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    set_ff_config(config)

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'active'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'completed'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 0


def test_cov_with_duplicates():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    config.checks.connascence_of_value.min_occurrences = 2
    set_ff_config(config)

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'active'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'Active'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 2

    finding_models = {f.model for f in findings}
    assert finding_models == {"model1", "model2"}
    assert all(f.check == "connascence_of_value" for f in findings)
    assert all(f.severity == "warning" for f in findings)
    
    # Original case preserved per model
    m1_finding = [f for f in findings if f.model == "model1"][0]
    m2_finding = [f for f in findings if f.model == "model2"][0]
    
    assert "Literal 'active'" in m1_finding.message
    assert "Literal 'Active'" in m2_finding.message


def test_cov_ignored_values():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    # 'active' is now ignored
    config.checks.connascence_of_value.ignored_values = ["0", "1", "", "active"]
    set_ff_config(config)

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'active' AND val = 0",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'active' AND val = 0",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 0


def test_cov_negated_literals():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    set_ff_config(config)

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE val = -5",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE val = -5",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 2
    assert "Literal '-5'" in findings[0].message


def test_cov_limit_offset_ignored():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    set_ff_config(config)

    # 100 and 10 are duplicated in LIMIT and OFFSET
    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} LIMIT 100 OFFSET 10",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} LIMIT 100 OFFSET 10",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 0


def test_cov_layer_filtering():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    config.checks.connascence_of_value.skip_layers = ["sources"]
    set_ff_config(config)

    # sources/model1.sql is in 'sources' layer, marts/model2.sql is in 'marts' layer.
    model1 = ModelRepresentation(
        name="model1",
        path="models/sources/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'active'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'active'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    # Ignored because model1 is skipped due to layer filtering, so only model2 has it (1 occurrence < min_occurrences)
    assert len(findings) == 0


def test_cov_disabled():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = False
    set_ff_config(config)

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'active'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'active'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 0


def test_cov_unparseable_query():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    set_ff_config(config)

    # model with unparseable query (syntax error causing parsed to be None)
    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM WHERE",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'active'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 0


def test_cov_duplicate_within_single_model():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    set_ff_config(config)

    # status = 'active' occurs twice in model1, but only once in model2.
    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'active' OR status2 = 'active'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'active'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 2


def test_cov_multiple_other_occurrences():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    config.checks.connascence_of_value.min_occurrences = 2
    set_ff_config(config)

    # literal duplicated across 4 models (so 3 other occurrences for each)
    models = {}
    for i in range(1, 5):
        models[f"model{i}"] = ModelRepresentation(
            name=f"model{i}",
            path=f"models/marts/model{i}.sql",
            dialect="postgres",
            query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'active'",
        )

    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 4
    
    # Message should use oxford comma list
    finding_m1 = [f for f in findings if f.model == "model1"][0]
    assert "model 'model2', model 'model3', and model 'model4'" in finding_m1.message
