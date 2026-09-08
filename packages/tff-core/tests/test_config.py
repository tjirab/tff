"""Tests for fitness_functions.yaml loading and merging."""

from pathlib import Path

import pytest

from tff.core.config import (
    FitnessFunctionsConfig,
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


def test_rule_config_injection_and_deprecation():
    import warnings
    from tff.core.rules.base import Rule
    from tff.core.config import FitnessFunctionsConfig

    cfg = FitnessFunctionsConfig()
    rule = Rule(config=cfg)
    assert rule.config is cfg

    new_cfg = FitnessFunctionsConfig()
    rule.config = new_cfg
    assert rule.config is new_cfg

    # Unbound rule should emit DeprecationWarning on .config
    unbound_rule = Rule()
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        fallback_cfg = unbound_rule.config
        assert fallback_cfg is not None
        deprecation_warnings = [
            item for item in w if issubclass(item.category, DeprecationWarning)
        ]
        assert len(deprecation_warnings) >= 1
        assert "get_ff_config() is deprecated" in str(deprecation_warnings[0].message)


