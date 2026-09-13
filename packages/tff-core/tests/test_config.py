"""Tests for fitness_functions.yaml loading and merging."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from tff.core.config import (
    DEFAULT_LAYER_ORDER,
    MISSING_CONFIG_NOTICE,
    STARTER_CONFIG_YAML,
    FitnessFunctionsConfig,
    init_fitness_config,
    load_fitness_config,
    resolve_project_path,
)


def test_load_defaults_without_file(tmp_path: Path) -> None:
    config = load_fitness_config(tmp_path, config_path="missing.yaml")
    assert config.checks.layer_integrity.enabled is True
    assert config.rules.sql_complexity.thresholds["cte_count"] == [8, 12]


def test_load_yaml_and_merge_overrides(tmp_path: Path) -> None:
    yaml_path = tmp_path / "fitness_functions.yaml"
    yaml_path.write_text(
        """
checks:
  dependency_graph:
    fan_out_warn: 20
rules:
  column_names:
    replacements:
      bad: good
""",
        encoding="utf-8",
    )
    config = load_fitness_config(
        tmp_path,
        overrides={"checks": {"dependency_graph": {"fan_out_fail": 30}}},
    )
    assert config.checks.dependency_graph.fan_out_warn == 20
    assert config.checks.dependency_graph.fan_out_fail == 30
    assert config.rules.column_names.replacements == {"bad": "good"}


def _config_with_root(project_root: Path) -> FitnessFunctionsConfig:
    config = FitnessFunctionsConfig()
    config._project_root = project_root  # type: ignore[attr-defined]
    return config


def test_resolve_project_path_valid_relative(tmp_path: Path) -> None:
    nested = tmp_path / "models" / "core"
    nested.mkdir(parents=True)
    config = _config_with_root(tmp_path)

    resolved = resolve_project_path(config, "models/core")

    assert resolved == nested.resolve()


def test_resolve_project_path_rejects_parent_escape(tmp_path: Path) -> None:
    config = _config_with_root(tmp_path)

    with pytest.raises(ValueError, match="resolves outside project root"):
        resolve_project_path(config, "../outside")


def test_resolve_project_path_rejects_absolute_outside_root(tmp_path: Path) -> None:
    config = _config_with_root(tmp_path)

    with pytest.raises(ValueError, match="resolves outside project root"):
        resolve_project_path(config, "/etc/passwd")


def test_resolve_project_path_allows_absolute_inside_root(tmp_path: Path) -> None:
    nested = tmp_path / "contracts.json"
    nested.write_text("{}", encoding="utf-8")
    config = _config_with_root(tmp_path)

    resolved = resolve_project_path(config, str(nested))

    assert resolved == nested.resolve()


def test_layer_filter_config_parsing(tmp_path: Path) -> None:
    yaml_path = tmp_path / "fitness_functions.yaml"
    yaml_path.write_text(
        """
rules:
  ban_select_star:
    enabled: true
    skip_layers: [sources]
    only_layers: [core, marts]
""",
        encoding="utf-8",
    )
    config = load_fitness_config(tmp_path)
    rule_config = config.rules.ban_select_star
    assert rule_config.enabled is True
    assert rule_config.skip_layers == ["sources"]
    assert rule_config.only_layers == ["core", "marts"]

    assert rule_config.should_run("core") is True
    assert rule_config.should_run("sources") is False
    assert rule_config.should_run("derived") is False

    # Test enabled = False
    rule_config.enabled = False
    assert rule_config.should_run("core") is False
    assert rule_config.should_run(None) is False


def test_no_positional_group_by_or_order_by_config_parsing(tmp_path: Path) -> None:
    yaml_path = tmp_path / "fitness_functions.yaml"
    yaml_path.write_text(
        """
rules:
  no_positional_group_by_or_order_by:
    enabled: true
    skip_layers: [sources]
    only_layers: [core, marts]
""",
        encoding="utf-8",
    )
    config = load_fitness_config(tmp_path)
    rule_config = config.rules.no_positional_group_by_or_order_by
    assert rule_config.enabled is True
    assert rule_config.skip_layers == ["sources"]
    assert rule_config.only_layers == ["core", "marts"]

    assert rule_config.should_run("core") is True
    assert rule_config.should_run("sources") is False
    assert rule_config.should_run("derived") is False


def test_environment_agnostic_references_config_parsing(tmp_path: Path) -> None:
    yaml_path = tmp_path / "fitness_functions.yaml"
    yaml_path.write_text(
        """
rules:
  environment_agnostic_references:
    enabled: true
    banned_environments: [prod, custom]
    skip_layers: [sources]
    only_layers: [core, marts]
""",
        encoding="utf-8",
    )
    config = load_fitness_config(tmp_path)
    rule_config = config.rules.environment_agnostic_references
    assert rule_config.enabled is True
    assert rule_config.banned_environments == ["prod", "custom"]
    assert rule_config.skip_layers == ["sources"]
    assert rule_config.only_layers == ["core", "marts"]

    assert rule_config.should_run("core") is True
    assert rule_config.should_run("sources") is False
    assert rule_config.should_run("derived") is False


def test_schema_contract_models_parsing():
    from tff.core.config import (
        ColumnParityMember,
        ColumnParityGroup,
        DimensionParityTarget,
        DimensionParityGroup,
        ContractGroupsConfig,
    )

    # ColumnParityMember
    member = ColumnParityMember(file="models/dim_a.sql")
    assert member.file == "models/dim_a.sql"

    target = DimensionParityTarget(file="models/dim_b.sql")
    assert target.file == "models/dim_b.sql"

    # ColumnParityGroup with string shorthand members
    group = ColumnParityGroup(
        reference="models/ref.sql",
        members=["models/m1.sql", {"file": "models/m2.sql", "substitutions": {"x": "y"}}],
    )
    assert len(group.members) == 2
    assert group.members[0].file == "models/m1.sql"
    assert group.members[1].file == "models/m2.sql"
    assert group.members[1].substitutions == {"x": "y"}

    # DimensionParityGroup with string shorthand targets
    dim_group = DimensionParityGroup(
        left="models/left.sql",
        right={"file": "models/right.sql", "exclude_columns": ["col1"]},
    )
    assert dim_group.left.file == "models/left.sql"
    assert dim_group.right.file == "models/right.sql"
    assert dim_group.right.exclude_columns == ["col1"]

    # ContractGroupsConfig
    cg = ContractGroupsConfig(
        column_parity_groups=[group],
        dimension_parity_groups=[dim_group],
    )
    assert len(cg.column_parity_groups) == 1
    assert len(cg.dimension_parity_groups) == 1

    # Validator branch coverage
    assert ColumnParityGroup.validate_members(None) is None
    assert DimensionParityGroup.validate_target({"file": "m.sql"}) == {"file": "m.sql"}


def test_yaml_config_with_contract_groups_and_exclusions(tmp_path: Path):
    yaml_path = tmp_path / "fitness_functions.yaml"
    yaml_path.write_text(
        """
contract_groups:
  column_parity_groups:
    - reference: models/ref.sql
      members:
        - models/m1.sql
  dimension_parity_groups:
    - left: models/left.sql
      right: models/right.sql

exclusions:
  - source_layer: core
    target_layer: derived

allowed_exceptions:
  - model: derived.m1
    dependency: core.m2
""",
        encoding="utf-8",
    )
    config = load_fitness_config(tmp_path)
    assert config.contract_groups is not None
    assert len(config.contract_groups.column_parity_groups) == 1
    assert len(config.contract_groups.dimension_parity_groups) == 1
    assert len(config.exclusions) == 1
    assert config.exclusions[0].source_layer == "core"
    assert len(config.allowed_exceptions) == 1
    assert config.allowed_exceptions[0].model == "derived.m1"


def test_rule_config_injection():
    import warnings
    from tff.core.rules.base import Rule
    from tff.core.config import FitnessFunctionsConfig

    cfg = FitnessFunctionsConfig()
    rule = Rule(config=cfg)
    assert rule.config is cfg

    new_cfg = FitnessFunctionsConfig()
    rule.config = new_cfg
    assert rule.config is new_cfg

    rule.config = None
    assert isinstance(rule.config, FitnessFunctionsConfig)

    # Unbound rule should cleanly default to FitnessFunctionsConfig without emitting DeprecationWarning
    unbound_rule = Rule()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        fallback_cfg = unbound_rule.config
        assert isinstance(fallback_cfg, FitnessFunctionsConfig)
        deprecation_warnings = [
            item for item in w if issubclass(item.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) == 0


def test_context_deprecation():
    import warnings
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.context import clear_ff_config, get_ff_config, set_ff_config

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        cfg = FitnessFunctionsConfig()
        set_ff_config(cfg)
        retrieved = get_ff_config()
        assert retrieved is cfg
        clear_ff_config()

        messages = [str(item.message) for item in w if issubclass(item.category, DeprecationWarning)]
        assert any("set_ff_config() is deprecated" in msg for msg in messages)
        assert any("get_ff_config() is deprecated" in msg for msg in messages)
        assert any("clear_ff_config() is deprecated" in msg for msg in messages)


def test_default_layer_hierarchy(tmp_path: Path):
    from tff.core.config import LayersConfig

    assert DEFAULT_LAYER_ORDER == ["staging", "intermediate", "core", "marts"]
    assert LayersConfig().order == ["staging", "intermediate", "core", "marts"]
    assert "No fitness_functions.yaml found" in MISSING_CONFIG_NOTICE
    assert "tff init" in MISSING_CONFIG_NOTICE

    # Loading without a config file falls back to defaults
    config = load_fitness_config(tmp_path, config_path="missing.yaml")
    assert config.layers.order == ["staging", "intermediate", "core", "marts"]
    assert config.config_file_found is False

    # Check core rules enabled by default
    assert config.rules.ban_select_star.enabled is True
    assert config.checks.layer_integrity.enabled is True
    assert config.checks.duplicate_ctes.enabled is True
    assert config.rules.no_positional_group_by_or_order_by.enabled is True
    assert config.rules.environment_agnostic_references.enabled is True
    assert config.rules.metadata.enabled is True
    assert config.rules.metadata.owner is True
    assert config.rules.metadata.description is True
    assert config.rules.metadata.grain is True
    assert config.rules.metadata.not_null is True
    assert config.rules.metadata.unique_values is True


def test_config_file_found_flag(tmp_path: Path):
    config_file = tmp_path / "fitness_functions.yaml"
    config_file.write_text("layers:\n  order: [staging, marts]\n", encoding="utf-8")

    config = load_fitness_config(tmp_path)
    assert config.config_file_found is True
    assert config.layers.order == ["staging", "marts"]


def test_init_fitness_config_success(tmp_path: Path):
    created_path = init_fitness_config(tmp_path)
    assert created_path.exists()
    assert created_path == tmp_path / "fitness_functions.yaml"
    assert created_path.read_text(encoding="utf-8") == STARTER_CONFIG_YAML

    # Verify that the generated YAML loads and validates cleanly
    loaded_config = load_fitness_config(tmp_path)
    assert loaded_config.config_file_found is True
    assert loaded_config.layers.order == ["staging", "intermediate", "core", "marts"]
    assert loaded_config.checks.layer_integrity.enabled is True
    assert loaded_config.rules.ban_select_star.enabled is True
    assert loaded_config.rules.no_positional_group_by_or_order_by.enabled is True
    assert loaded_config.rules.environment_agnostic_references.enabled is True


def test_init_fitness_config_already_exists(tmp_path: Path):
    init_fitness_config(tmp_path)
    assert (tmp_path / "fitness_functions.yaml").exists()

    with pytest.raises(FileExistsError, match="already exists"):
        init_fitness_config(tmp_path, force=False)


def test_init_fitness_config_force_overwrite(tmp_path: Path):
    config_path = init_fitness_config(tmp_path)
    config_path.write_text("modified: true\n", encoding="utf-8")
    assert "modified: true" in config_path.read_text(encoding="utf-8")

    overwritten_path = init_fitness_config(tmp_path, force=True)
    assert overwritten_path.read_text(encoding="utf-8") == STARTER_CONFIG_YAML


def test_health_config_validation(tmp_path: Path):
    # Valid configuration
    valid_yaml = tmp_path / "fitness_functions.yaml"
    valid_yaml.write_text(
        """
health:
  weights:
    layer_integrity: 3.0
    schema_contracts: 2.0
    column_names: 0.5
  penalties:
    error: 1.5
    warning: 0.25
    project_error: 40.0
    project_warning: 15.0
""",
        encoding="utf-8",
    )
    config = load_fitness_config(tmp_path)
    assert config.health.weights["layer_integrity"] == 3.0
    assert config.health.weights["schema_contracts"] == 2.0
    assert config.health.weights["column_names"] == 0.5
    assert config.health.penalties.error == 1.5
    assert config.health.penalties.warning == 0.25
    assert config.health.penalties.project_error == 40.0
    assert config.health.penalties.project_warning == 15.0

    # Negative weights rejected
    with pytest.raises(ValueError, match="Weight for 'layer_integrity' must be non-negative"):
        FitnessFunctionsConfig.model_validate({
            "health": {"weights": {"layer_integrity": -1.0}}
        })

    with pytest.raises(ValueError, match="Weight for 'Dynamic Coupling' must be non-negative"):
        FitnessFunctionsConfig.model_validate({
            "health": {"category_weights": {"Dynamic Coupling": -0.5}}
        })

    # Negative penalty rejected
    with pytest.raises(ValueError):
        FitnessFunctionsConfig.model_validate({
            "health": {"penalties": {"error": -1.0}}
        })

    # Non-dict weights / category_weights validator coverage
    health_empty = FitnessFunctionsConfig.model_validate({
        "health": {"weights": None, "category_weights": None}
    })
    assert health_empty.health.weights == {}

    with pytest.raises(Exception):
        FitnessFunctionsConfig.model_validate({
            "health": {"weights": "not-a-dict"}
        })

    # Check penalties with ratio for project-level check
    ratio_cfg = FitnessFunctionsConfig.model_validate({
        "health": {
            "penalties": {
                "checks": {
                    "layer_integrity": {"error": 0.25, "warning": 0.10}
                }
            }
        }
    })
    assert ratio_cfg.health.penalties.get_check_error_penalty("layer_integrity", is_project_level=True) == 25.0
    assert ratio_cfg.health.penalties.get_check_warning_penalty("layer_integrity", is_project_level=True) == 10.0


def test_fitness_config_plugins(tmp_path: Path):
    from tff.core.config import FitnessFunctionsConfig, STARTER_CONFIG_YAML, load_fitness_config
    from tff.core.registry import registry

    # 1. plugins as list
    cfg1 = FitnessFunctionsConfig(plugins=["plugin1.py", "plugin2.py"])
    assert cfg1.plugins == ["plugin1.py", "plugin2.py"]

    # 2. plugins as single string normalized
    cfg2 = FitnessFunctionsConfig.model_validate({"plugins": "single_plugin.py"})
    assert cfg2.plugins == ["single_plugin.py"]

    # 3. plugins as None normalized to empty list
    cfg3 = FitnessFunctionsConfig.model_validate({"plugins": None})
    assert cfg3.plugins == []

    # Invalid plugins type raises ValidationError
    with pytest.raises(ValidationError):
        FitnessFunctionsConfig.model_validate({"plugins": 123})

    # 4. STARTER_CONFIG_YAML contains plugins comment
    assert "# plugins:" in STARTER_CONFIG_YAML

    # 5. load_fitness_config triggers plugin loading
    plugin_file = tmp_path / "cfg_test_plugin.py"
    plugin_file.write_text(
        """from tff.core.rules.base import Rule
class CfgTestRule(Rule):
    name = "cfg_test_rule"
    def check_model(self, model):
        return None
""",
        encoding="utf-8",
    )

    yaml_file = tmp_path / "fitness_functions.yaml"
    yaml_file.write_text(
        f"""plugins:
  - "{plugin_file.name}"
""",
        encoding="utf-8",
    )

    loaded_cfg = load_fitness_config(tmp_path)
    assert loaded_cfg.plugins == [plugin_file.name]
    assert registry.get("cfg_test_rule") is not None


def test_rule_get_rule_config():
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.rules.base import Rule

    class TestCustomRule(Rule):
        name = "test_custom_rule"

    cfg = FitnessFunctionsConfig.model_validate({
        "rules": {
            "test_custom_rule": {"threshold": 42, "enabled": True},
            "other_rule": {"threshold": 100},
        }
    })

    rule = TestCustomRule(config=cfg)
    rule_cfg = rule.get_rule_config()
    assert rule_cfg == {"threshold": 42, "enabled": True}

    # Match via explicit rule_name
    assert rule.get_rule_config("other_rule") == {"threshold": 100}

    # Unknown rule config returns None
    assert rule.get_rule_config("nonexistent_rule") is None

    # Builtin rule name (e.g. ban_select_star) returns direct attribute
    assert rule.get_rule_config("ban_select_star") is cfg.rules.ban_select_star

    # Rule without config
    rule_bare = TestCustomRule()
    rule_bare._config = None
    rule_bare.config.rules = None  # type: ignore[assignment]
    assert rule_bare.get_rule_config() is None


def test_config_workers_and_cache():
    cfg = FitnessFunctionsConfig(workers=4, cache_ast=False, cache_dir=".custom_cache")
    assert cfg.workers == 4
    assert cfg.cache_ast is False
    assert cfg.cache_dir == ".custom_cache"

    # String converted to int
    cfg_str = FitnessFunctionsConfig(workers="2")
    assert cfg_str.workers == 2

    # None allowed
    cfg_none = FitnessFunctionsConfig(workers=None)
    assert cfg_none.workers is None

    # Invalid workers < 1 raises ValidationError
    with pytest.raises(ValidationError, match="workers must be at least 1"):
        FitnessFunctionsConfig(workers=0)






