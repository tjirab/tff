from pathlib import Path
from unittest.mock import MagicMock
from sqlmesh.core.model import Model as SqlMeshModel

from tff.core.config import load_fitness_config, FitnessFunctionsConfig
from tff.core.context import set_ff_config
from tff.core.rules import ALL_RULES
from tff.sqlmesh.loader import map_sqlmesh_model, wrap_core_rule, FitnessLoader


def test_all_rules_have_unique_names() -> None:
    names = [rule.name for rule in ALL_RULES]
    assert len(names) == len(set(names))
    assert "classificationmacros" in names
    assert "martmodelnamingconvention" in names


def test_load_fitness_config_from_fixture(tmp_path: Path) -> None:
    yaml_path = tmp_path / "fitness_functions.yaml"
    yaml_path.write_text("checks:\n  layer_integrity:\n    enabled: false\n", encoding="utf-8")
    config = load_fitness_config(tmp_path, config_path=yaml_path)
    set_ff_config(config)
    assert config.checks.layer_integrity.enabled is False


def test_map_sqlmesh_model_with_audits() -> None:
    mock_model = MagicMock(spec=SqlMeshModel)
    mock_model.name = "my_model"
    mock_model._path = Path("models/my_model.sql")
    mock_model.dialect = "duckdb"
    mock_model.kind = MagicMock()
    mock_model.kind.is_symbolic = False
    mock_model.kind.name = "FULL"
    mock_model.columns_to_types = {"id": "int"}
    mock_model.depends_on = {"dep_model"}
    mock_model.description = "My desc"
    mock_model.owner = "data-team"
    mock_model.grains = ["id"]
    mock_model.audits = [("not_null", {"column": "id"})]

    model_rep = map_sqlmesh_model(mock_model)
    assert model_rep.name == "my_model"
    assert model_rep.audits == [("not_null", {"column": "id"})]


def test_wrapped_rule_execution() -> None:
    from tff.core.rules.no_select_star import NoSelectStar

    config = FitnessFunctionsConfig()
    config.rules.no_select_star.enabled = True
    set_ff_config(config)

    WrappedRuleClass = wrap_core_rule(NoSelectStar)
    rule_instance = WrappedRuleClass(context=MagicMock())

    mock_model = MagicMock(spec=SqlMeshModel)
    mock_model.name = "my_model"
    mock_model._path = Path("models/my_model.sql")
    mock_model.dialect = "duckdb"
    mock_model.kind = MagicMock()
    mock_model.kind.is_symbolic = False
    mock_model.kind.name = "FULL"
    mock_model.columns_to_types = {}
    mock_model.depends_on = set()
    mock_model.description = None
    mock_model.owner = None
    mock_model.grains = []
    mock_model.audits = []

    from unittest.mock import patch
    with patch("tff.core.rules.no_select_star.Path.exists", return_value=True), \
         patch("tff.core.rules.no_select_star.Path.read_text", return_value="SELECT * FROM table"):
        violation = rule_instance.check_model(mock_model)
        assert violation is not None
        assert "SELECT * is prohibited" in str(violation)


def test_fitness_loader_integration() -> None:
    from sqlmesh.core.context import Context

    fixture_path = Path(__file__).parent / "fixtures" / "minimal_project"
    context = Context(paths=[str(fixture_path)], loader=FitnessLoader)

    # Verify that the FitnessLoader configured fitness settings
    assert context._loaders[0]._ff_config.checks.layer_integrity.enabled is True

    # Verify that it registered the rules into SQLMesh linter
    linter = context._linters.get("")
    assert linter is not None
    rule_names = set(linter.rules)
    assert "classificationmacros" in rule_names
    assert "sqlcomplexity" in rule_names
    # Verify local custom dummy rule was loaded
    assert "customdummyrule" in rule_names
