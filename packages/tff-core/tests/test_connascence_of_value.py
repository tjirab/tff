
from sqlglot import exp
from tff.core.checks.connascence_of_value import (
    collect_connascence_of_value_findings,
    is_ignored_literal,
)
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation


def test_cov_no_duplicates():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True

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
    assert all(f.path is not None and "models/marts" in f.path for f in findings)
    
    # Original case preserved per model
    m1_finding = [f for f in findings if f.model == "model1"][0]
    m2_finding = [f for f in findings if f.model == "model2"][0]
    
    assert "Literal 'active'" in m1_finding.message
    assert "Literal 'Active'" in m2_finding.message
    assert "(CoV)" in m1_finding.message
    assert "Centralize via macro, seed, or upstream model." in m1_finding.message
    assert "https://tff.readthedocs.io/en/latest/rules_and_checks/#connascence-of-value-connascence_of_value" in m1_finding.message


def test_cov_ignored_values():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    # 'active' is now ignored
    config.checks.connascence_of_value.ignored_values = ["0", "1", "", "active"]

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


def test_cov_structural_sql_literals_ignored():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True

    queries = [
        "SELECT md5(a || '|' || b) as uuid FROM {{ ref('stg_a') }}",
        "SELECT round(x / 100.00, 2) FROM {{ ref('stg_a') }}",
        "SELECT cast(x as decimal(15, 2)) FROM {{ ref('stg_a') }}",
        "SELECT x::decimal(15, 2) FROM {{ ref('stg_a') }}",
        "SELECT split_part(email, '@', 2) FROM {{ ref('stg_a') }}",
        "SELECT substring(name, 1, 10), left(name, 5), right(name, 5) FROM {{ ref('stg_a') }}",
        "SELECT concat_ws('/', a, b) FROM {{ ref('stg_a') }}",
        "SELECT round(amount, -2) FROM {{ ref('stg_a') }}",
        "SELECT amount / (100.00) FROM {{ ref('stg_a') }}",
    ]

    for q in queries:
        model1 = ModelRepresentation(
            name="model1",
            path="models/marts/model1.sql",
            dialect="postgres",
            query=q,
        )
        model2 = ModelRepresentation(
            name="model2",
            path="models/marts/model2.sql",
            dialect="postgres",
            query=q,
        )
        models = {"model1": model1, "model2": model2}
        findings = collect_connascence_of_value_findings(models, config)
        assert len(findings) == 0, f"Expected 0 findings for query: {q}, got: {findings}"


def test_cov_domain_reuse_fixtures_warn():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    config.checks.connascence_of_value.min_occurrences = 2

    # 1. WHERE status = 'premium'
    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE status = 'premium'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE status = 'premium'",
    )
    findings = collect_connascence_of_value_findings({"model1": model1, "model2": model2}, config)
    assert len(findings) == 2
    assert all("premium" in f.message for f in findings)

    # 2. decode(tech_id, 2, '<value>', 'default')
    model3 = ModelRepresentation(
        name="model3",
        path="models/marts/model3.sql",
        dialect="postgres",
        query="SELECT decode(tech_id, 2, '<value>', 'default') FROM {{ ref('stg_a') }}",
    )
    model4 = ModelRepresentation(
        name="model4",
        path="models/marts/model4.sql",
        dialect="postgres",
        query="SELECT decode(tech_id, 2, '<value>', 'default') FROM {{ ref('stg_b') }}",
    )
    findings_decode = collect_connascence_of_value_findings({"model3": model3, "model4": model4}, config)
    # Literals 2, '<value>', and 'default' are duplicated across model3 and model4
    flagged_literals = {f.message for f in findings_decode}
    assert any("Literal '2'" in msg for msg in flagged_literals)
    assert any("Literal '<value>'" in msg for msg in flagged_literals)
    assert any("Literal 'default'" in msg for msg in flagged_literals)


def test_cov_ignored_punctuation():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT col1 || ' - ' || col2, col3 || ':' || col4 FROM {{ ref('stg_a') }}",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT col1 || ' - ' || col2, col3 || ':' || col4 FROM {{ ref('stg_b') }}",
    )
    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 0

    # If ignored_punctuation is cleared, punctuation characters trigger if duplicated
    config.checks.connascence_of_value.ignored_punctuation = []
    # Test with a standalone punctuation string not in DPipe
    model3 = ModelRepresentation(
        name="model3",
        path="models/marts/model3.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE delim = ':'",
    )
    model4 = ModelRepresentation(
        name="model4",
        path="models/marts/model4.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE delim = ':'",
    )
    findings_punct = collect_connascence_of_value_findings({"model3": model3, "model4": model4}, config)
    assert len(findings_punct) == 2
    assert "Literal ':'" in findings_punct[0].message


def test_cov_negated_with_parentheses():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE val = -(99)",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE val = -(99)",
    )
    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 2
    assert "Literal '-99'" in findings[0].message


def test_is_ignored_literal_standalone_node():
    node = exp.Literal.number(42)
    assert is_ignored_literal(node) is False


def test_cov_does_not_rewrite_email_or_regex_at_symbols():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    config.checks.connascence_of_value.min_occurrences = 2

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE regexp_like(email, '.@gmail.com')",
        provider="dbt",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE regexp_like(email, '.@gmail.com')",
        provider="dbt",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)
    assert len(findings) == 2
    for f in findings:
        assert "__sqlmesh_macro__" not in f.message
        assert "Literal '.@gmail.com'" in f.message

    # Also test without provider specified (defaulting to provider=None)
    model3 = ModelRepresentation(
        name="model3",
        path="models/marts/model3.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE email = 'support@company.com'",
    )
    model4 = ModelRepresentation(
        name="model4",
        path="models/marts/model4.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE email = 'support@company.com'",
    )
    findings_none = collect_connascence_of_value_findings({"model3": model3, "model4": model4}, config)
    assert len(findings_none) == 2
    for f in findings_none:
        assert "__sqlmesh_macro__" not in f.message
        assert "Literal 'support@company.com'" in f.message


def test_cov_min_length_ignores_tiny_string_literals():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    config.checks.connascence_of_value.min_occurrences = 2
    config.checks.connascence_of_value.min_length = 3
    # Clear ignored_values to verify min_length alone ignores '0', '-1', '', '3'
    config.checks.connascence_of_value.ignored_values = []

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE code = '0' AND status = '-1' AND flag = '' AND typ = '3' AND category = 'active'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE code = '0' AND status = '-1' AND flag = '' AND typ = '3' AND category = 'active'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)

    # Only 'active' (len 6 >= 3) should trigger findings; '0', '-1', '', '3' are ignored
    assert len(findings) == 2
    for f in findings:
        assert "Literal 'active'" in f.message
        assert "Literal '0'" not in f.message
        assert "Literal '-1'" not in f.message
        assert "Literal ''" not in f.message
        assert "Literal '3'" not in f.message


def test_cov_min_length_does_not_ignore_numbers():
    config = FitnessFunctionsConfig()
    config.checks.connascence_of_value.enabled = True
    config.checks.connascence_of_value.min_occurrences = 2
    config.checks.connascence_of_value.min_length = 5
    config.checks.connascence_of_value.ignored_values = []

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE id = 42 AND str_val = 'hi'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE id = 42 AND str_val = 'hi'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)

    # 42 is a numeric literal so min_length does not ignore it; 'hi' is string len 2 < 5 so it is ignored
    assert len(findings) == 2
    for f in findings:
        assert "Literal '42'" in f.message
        assert "Literal 'hi'" not in f.message


def test_cov_min_string_length_alias():
    config = FitnessFunctionsConfig.model_validate({
        "checks": {
            "connascence_of_value": {
                "enabled": True,
                "min_occurrences": 2,
                "min_string_length": 4,
                "ignored_values": [],
            }
        }
    })
    assert config.checks.connascence_of_value.min_length == 4

    model1 = ModelRepresentation(
        name="model1",
        path="models/marts/model1.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_a') }} WHERE val = 'abc' AND cat = 'good'",
    )
    model2 = ModelRepresentation(
        name="model2",
        path="models/marts/model2.sql",
        dialect="postgres",
        query="SELECT * FROM {{ ref('stg_b') }} WHERE val = 'abc' AND cat = 'good'",
    )

    models = {"model1": model1, "model2": model2}
    findings = collect_connascence_of_value_findings(models, config)

    # 'abc' (len 3 < 4) ignored; 'good' (len 4 >= 4) flagged
    assert len(findings) == 2
    for f in findings:
        assert "Literal 'good'" in f.message
        assert "Literal 'abc'" not in f.message


