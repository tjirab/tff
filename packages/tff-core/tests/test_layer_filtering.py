from pathlib import Path

from tff.core.checks.dependency_graph import collect_dependency_graph_findings
from tff.core.config import FitnessFunctionsConfig, ColumnTypeRuleEntry
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules import (
    ClassificationMacros,
    ColumnNames,
    ColumnTypes,
    FilenameEqualsModelname,
    NoMissingDescription,
    NoMissingGrain,
    NoMissingNotNull,
    NoMissingOwner,
    NoMissingUniqueValues,
    NoSelectStar,
    SqlComplexity,
)


def test_rules_respect_layer_filtering(tmp_path: Path):
    config = FitnessFunctionsConfig()

    # Configure all rules to be enabled but skip "sources" layer
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.skip_layers = ["sources"]

    config.rules.column_names.enabled = True
    config.rules.column_names.skip_layers = ["sources"]
    config.rules.column_names.replacements = {"api_request": "api_call"}

    config.rules.column_types.enabled = True
    config.rules.column_types.skip_layers = ["sources"]
    config.rules.column_types.rules = [
        ColumnTypeRuleEntry(name="id_is_text", pattern="_id$", data_type="text")
    ]

    config.rules.filename_equals_modelname.enabled = True
    config.rules.filename_equals_modelname.skip_layers = ["sources"]

    config.rules.metadata.enabled = True
    config.rules.metadata.skip_layers = ["sources"]
    config.rules.metadata.owner = True
    config.rules.metadata.description = True
    config.rules.metadata.grain = True
    config.rules.metadata.not_null = True
    config.rules.metadata.unique_values = True

    config.rules.sql_complexity.enabled = True
    config.rules.sql_complexity.skip_layers = ["sources"]

    config.rules.no_select_star.enabled = True
    config.rules.no_select_star.skip_layers = ["sources"]

    set_ff_config(config)

    # Create temporary SQL file for file-reading checks
    sql_file = tmp_path / "models/sources/my_model.sql"
    sql_file.parent.mkdir(parents=True, exist_ok=True)
    sql_file.write_text("SELECT * FROM table", encoding="utf-8")

    # Mock a model in the skipped "sources" layer
    model = ModelRepresentation(
        name="sources.my_model",
        path=str(sql_file),
        is_symbolic=False,
        columns_to_types={"api_request": "int", "user_id": "int"},
        audits=[],
        owner=None,
        description=None,
        grains=[],
    )

    rules = [
        ClassificationMacros(),
        ColumnNames(),
        ColumnTypes(),
        FilenameEqualsModelname(),
        NoMissingOwner(),
        NoMissingDescription(),
        NoMissingGrain(),
        NoMissingNotNull(),
        NoMissingUniqueValues(),
        SqlComplexity(),
        NoSelectStar(),
    ]

    for rule in rules:
        assert rule.check_model(model) is None

    # Test when rules are disabled
    config.rules.filename_equals_modelname.enabled = False
    config.rules.metadata.enabled = False
    config.rules.no_select_star.enabled = False
    set_ff_config(config)

    # Mart model that would violate rules if enabled
    sql_file_marts = tmp_path / "models/marts/my_model.sql"
    sql_file_marts.parent.mkdir(parents=True, exist_ok=True)
    sql_file_marts.write_text("SELECT * FROM table", encoding="utf-8")

    model_marts = ModelRepresentation(
        name="marts.my_model_diff",
        path=str(sql_file_marts),
        is_symbolic=False,
    )

    assert FilenameEqualsModelname().check_model(model_marts) is None
    assert NoMissingOwner().check_model(model_marts) is None
    assert NoSelectStar().check_model(model_marts) is None


def test_dependency_graph_respects_layer_filtering():
    config = FitnessFunctionsConfig()
    config.checks.dependency_graph.enabled = True
    config.checks.dependency_graph.skip_layers = ["sources"]
    config.checks.dependency_graph.fan_in_warn = 1
    config.checks.dependency_graph.fan_out_warn = 1
    set_ff_config(config)

    # Mock models
    model1 = ModelRepresentation(
        name="sources.model1",
        path="models/sources/model1.sql",
        depends_on={"sources.model2"},
    )
    model2 = ModelRepresentation(
        name="sources.model2",
        path="models/sources/model2.sql",
    )

    models = {
        "sources.model1": model1,
        "sources.model2": model2,
    }

    findings = collect_dependency_graph_findings(models, config)
    assert len(findings) == 0
