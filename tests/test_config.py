"""Tests for fitness_functions.yaml loading and merging."""

from pathlib import Path

import pytest

from sqlmesh_ff.config import (
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
