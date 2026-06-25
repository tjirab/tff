"""Tests for fitness rule registration and config loading."""

from pathlib import Path

from sqlmesh_ff.config import load_fitness_config
from sqlmesh_ff.context import set_ff_config
from sqlmesh_ff.rules import ALL_RULES


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
