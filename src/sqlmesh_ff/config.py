"""Pydantic models and loaders for fitness_functions.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LayersConfig(BaseModel):
    order: list[str] = Field(
        default_factory=lambda: ["sources", "derived", "core", "marts", "export"]
    )


class CheckEnabled(BaseModel):
    enabled: bool = True


class DependencyGraphCheckConfig(CheckEnabled):
    fan_out_warn: int = 15
    fan_out_fail: int = 25
    fan_in_warn: int = 10


class ChecksConfig(BaseModel):
    layer_integrity: CheckEnabled = Field(default_factory=CheckEnabled)
    custom_exclusions: CheckEnabled = Field(default_factory=CheckEnabled)
    schema_contracts: CheckEnabled = Field(default_factory=CheckEnabled)
    dependency_graph: DependencyGraphCheckConfig = Field(
        default_factory=DependencyGraphCheckConfig
    )


class ClassificationMacrosRuleConfig(BaseModel):
    enabled: bool = True
    skip_layers: list[str] = Field(default_factory=lambda: ["sources"])
    columns: dict[str, str] = Field(
        default_factory=lambda: {
            "product_type": r"@product_type\b|@PRODUCT_TYPE\b",
            "billing_segment": r"@BILLING_SEGMENT\b|@billing_segment\b",
            "industry": r"@INDUSTRY\b|@industry\b",
        }
    )


class SqlComplexityRuleConfig(BaseModel):
    enabled: bool = True
    warn_only: bool = True
    thresholds: dict[str, list[int]] = Field(
        default_factory=lambda: {
            "decision_points": [15, 25],
            "cte_count": [8, 12],
            "join_count": [8, 12],
            "line_count": [250, 400],
        }
    )


class MartNamingRuleConfig(BaseModel):
    enabled: bool = True
    layer_name: str = "marts"
    rule: str = "prefix_with_subdirectory"


class ColumnNamesRuleConfig(BaseModel):
    enabled: bool = True
    replacements: dict[str, str] = Field(default_factory=dict)


class ColumnTypeRuleEntry(BaseModel):
    name: str
    pattern: str
    data_type: str


class ColumnTypesRuleConfig(BaseModel):
    enabled: bool = True
    rules: list[ColumnTypeRuleEntry] = Field(default_factory=list)
    equivalent_types: dict[str, list[str]] = Field(
        default_factory=lambda: {"text": ["text", "varchar"]}
    )


class MetadataRuleConfig(BaseModel):
    owner: bool = True
    description: bool = True
    grain: bool = True


class FilenameEqualsModelnameRuleConfig(BaseModel):
    enabled: bool = True


class RulesConfig(BaseModel):
    classification_macros: ClassificationMacrosRuleConfig = Field(
        default_factory=ClassificationMacrosRuleConfig
    )
    sql_complexity: SqlComplexityRuleConfig = Field(
        default_factory=SqlComplexityRuleConfig
    )
    mart_naming: MartNamingRuleConfig = Field(default_factory=MartNamingRuleConfig)
    column_names: ColumnNamesRuleConfig = Field(default_factory=ColumnNamesRuleConfig)
    column_types: ColumnTypesRuleConfig = Field(default_factory=ColumnTypesRuleConfig)
    metadata: MetadataRuleConfig = Field(default_factory=MetadataRuleConfig)
    filename_equals_modelname: FilenameEqualsModelnameRuleConfig = Field(
        default_factory=FilenameEqualsModelnameRuleConfig
    )


class FitnessFunctionsConfig(BaseModel):
    contract_groups_path: str = "linter_contract_groups.json"
    exclusions_path: str = "linter_exclusions.json"
    layers: LayersConfig = Field(default_factory=LayersConfig)
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_fitness_config(
    project_root: Path,
    config_path: str | Path | None = "fitness_functions.yaml",
    overrides: dict[str, Any] | None = None,
) -> FitnessFunctionsConfig:
    """Load fitness config with defaults, yaml file, and optional overrides."""
    data: dict[str, Any] = {}

    if config_path is not None:
        yaml_path = Path(config_path)
        if not yaml_path.is_absolute():
            yaml_path = project_root / yaml_path
        if yaml_path.exists():
            loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"Expected mapping in {yaml_path}")
            data = loaded

    if overrides:
        data = _deep_merge(data, overrides)

    config = FitnessFunctionsConfig.model_validate(data)
    config._project_root = project_root  # type: ignore[attr-defined]
    return config


def _ensure_under_root(path: Path, root: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise ValueError(
            f"Path {path} resolves outside project root {root}"
        ) from None
    return resolved


def resolve_project_path(config: FitnessFunctionsConfig, relative: str) -> Path:
    root: Path = getattr(config, "_project_root", Path.cwd())
    path = Path(relative)
    if path.is_absolute():
        return _ensure_under_root(path, root)
    return _ensure_under_root(root / path, root)
