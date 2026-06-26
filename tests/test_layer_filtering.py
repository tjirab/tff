from unittest.mock import MagicMock

from sqlglot import parse_one

from sqlmesh_ff.checks.dependency_graph import collect_dependency_graph_findings
from sqlmesh_ff.config import FitnessFunctionsConfig
from sqlmesh_ff.context import set_ff_config
from sqlmesh_ff.rules import (
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


def test_rules_respect_layer_filtering():
    config = FitnessFunctionsConfig()

    # Configure all rules to be enabled but skip "sources" layer
    config.rules.classification_macros.enabled = True
    config.rules.classification_macros.skip_layers = ["sources"]

    config.rules.column_names.enabled = True
    config.rules.column_names.skip_layers = ["sources"]
    config.rules.column_names.replacements = {"api_request": "api_call"}

    config.rules.column_types.enabled = True
    config.rules.column_types.skip_layers = ["sources"]
    from sqlmesh_ff.config import ColumnTypeRuleEntry

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

    # Mock a model in the skipped "sources" layer
    mock_source_model = MagicMock()
    mock_source_model._path = "models/sources/my_model.sql"
    mock_source_model.name = "sources.my_model"
    mock_source_model.query = parse_one("SELECT * FROM table")
    mock_source_model.columns_to_types = {"api_request": "int", "user_id": "int"}
    mock_source_model.audits = []
    mock_source_model.kind.is_symbolic = False
    mock_source_model.kind.is_external = False
    mock_source_model.owner = None
    mock_source_model.description = None
    mock_source_model.grains = []

    # Run check_model on the mock source model for all rules
    context_mock = MagicMock()

    rules = [
        ClassificationMacros(context=context_mock),
        ColumnNames(context=context_mock),
        ColumnTypes(context=context_mock),
        FilenameEqualsModelname(context=context_mock),
        NoMissingOwner(context=context_mock),
        NoMissingDescription(context=context_mock),
        NoMissingGrain(context=context_mock),
        NoMissingNotNull(context=context_mock),
        NoMissingUniqueValues(context=context_mock),
        SqlComplexity(context=context_mock),
        NoSelectStar(context=context_mock),
    ]

    for rule in rules:
        assert rule.check_model(mock_source_model) is None

    # Test when rules are disabled
    config.rules.filename_equals_modelname.enabled = False
    config.rules.metadata.enabled = False
    config.rules.no_select_star.enabled = False
    set_ff_config(config)

    # Even on non-skipped layer, if disabled, they should return None
    mock_marts_model = MagicMock()
    mock_marts_model._path = "models/marts/my_model.sql"
    mock_marts_model.name = "marts.my_model_diff"
    mock_marts_model.query = parse_one("SELECT * FROM table")
    mock_marts_model.columns_to_types = {}
    mock_marts_model.audits = []
    mock_marts_model.kind.is_symbolic = False
    mock_marts_model.kind.is_external = False
    mock_marts_model.owner = None
    mock_marts_model.description = None
    mock_marts_model.grains = []

    assert (
        FilenameEqualsModelname(context=context_mock).check_model(mock_marts_model)
        is None
    )
    assert NoMissingOwner(context=context_mock).check_model(mock_marts_model) is None
    assert NoSelectStar(context=context_mock).check_model(mock_marts_model) is None


def test_dependency_graph_respects_layer_filtering():
    config = FitnessFunctionsConfig()
    config.checks.dependency_graph.enabled = True
    config.checks.dependency_graph.skip_layers = ["sources"]
    config.checks.dependency_graph.fan_in_warn = 1
    config.checks.dependency_graph.fan_out_warn = 1
    set_ff_config(config)

    # Mock models
    model1 = MagicMock()
    model1.name = "sources.model1"
    model1._path = "models/sources/model1.sql"
    model1.depends_on = {"sources.model2"}
    model1.kind.is_symbolic = False

    model2 = MagicMock()
    model2.name = "sources.model2"
    model2._path = "models/sources/model2.sql"
    model2.depends_on = set()
    model2.kind.is_symbolic = False

    context = MagicMock()
    context.models = {"sources.model1": model1, "sources.model2": model2}
    context.get_model.side_effect = lambda name: {
        "sources.model1": model1,
        "sources.model2": model2,
    }.get(name)

    findings = collect_dependency_graph_findings(context, config)
    assert len(findings) == 0
