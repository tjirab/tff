"""Pydantic models and loaders for fitness_functions.yaml."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, PrivateAttr, field_validator

DEFAULT_LAYER_ORDER: list[str] = ["staging", "intermediate", "core", "marts"]

MISSING_CONFIG_NOTICE: str = (
    "Notice: No fitness_functions.yaml found. Running with default layer conventions (staging -> intermediate -> core -> marts).\n"
    "Run 'tff init' to generate a project configuration file."
)

STARTER_CONFIG_YAML: str = """# =============================================================================
# Transformation Fitness Functions (TFF) Configuration
# Documentation: https://github.com/tjirab/tff
# =============================================================================

# Define the architectural layer hierarchy (upstream -> downstream).
# Models in an upstream layer cannot depend on models in a downstream layer.
layers:
  order:
    - staging
    - intermediate
    - core
    - marts

# Project-level architectural and DAG checks
checks:
  # Enforce unidirectional dependencies between layers and domain boundaries in marts
  layer_integrity:
    enabled: true

  # Flag models with excessive fan-in (dependents) or fan-out (dependencies)
  dependency_graph:
    enabled: true
    fan_out_warn: 15
    fan_out_fail: 25
    fan_in_warn: 10

  # Warn on excessively deep chains of views / non-table materializations
  materialization_depth:
    enabled: true
    max_depth_warn: 3
    max_depth_fail: 5

  # Detect identical or duplicate CTEs across models
  duplicate_ctes:
    enabled: true
    severity: warning
    min_ast_nodes: 12

  # Detect repeated hardcoded literals and magic values across models
  connascence_of_value:
    enabled: true
    severity: warning
    min_occurrences: 2
    ignored_values: ["0", "1", ""]

# Model-level SQL rules
rules:
  # Prohibit 'SELECT *' to avoid silent breakage from upstream schema drift
  ban_select_star:
    enabled: true
    skip_layers: [sources]

  # Require explicit column names instead of positional references (e.g. GROUP BY 1, 2)
  no_positional_group_by_or_order_by:
    enabled: true
    skip_layers: [sources]

  # Prevent hardcoded environment prefixes/databases (e.g. prod, dev, uat)
  environment_agnostic_references:
    enabled: true
    banned_environments: [prod, dev, staging, uat, qa]

  # Enforce model documentation and metadata requirements
  metadata:
    enabled: true
    owner: true
    description: true
    grain: true
    not_null: true
    unique_values: true

  # Monitor SQL complexity (cyclomatic decision points, join count, line count)
  sql_complexity:
    enabled: true
    warn_only: true
    thresholds:
      decision_points: [15, 25]
      cte_count: [8, 12]
      join_count: [8, 12]
      line_count: [250, 400]

  # Require SQL model filename to match model name
  filename_equals_modelname:
    enabled: true

  # Mart model naming convention (e.g. prefix with subdirectory)
  mart_naming:
    enabled: true
    layer_name: marts
    rule: prefix_with_subdirectory
"""


class LayersConfig(BaseModel):
    order: list[str] = Field(
        default_factory=lambda: list(DEFAULT_LAYER_ORDER)
    )


class CheckEnabled(BaseModel):
    enabled: bool = True


class LayerFilterConfig(BaseModel):
    enabled: bool = True
    skip_layers: list[str] = Field(default_factory=list)
    only_layers: list[str] | None = None

    def should_run(self, layer: str | None) -> bool:
        if not self.enabled:
            return False
        if layer is None:
            return True
        if self.only_layers is not None:
            return layer in self.only_layers
        return layer not in self.skip_layers


class DependencyGraphCheckConfig(LayerFilterConfig):
    fan_out_warn: int = 15
    fan_out_fail: int = 25
    fan_in_warn: int = 10


class MaterializationDepthCheckConfig(LayerFilterConfig):
    max_depth_warn: int = 3
    max_depth_fail: int = 5


class DuplicateCtesCheckConfig(LayerFilterConfig):
    severity: str = "warning"
    min_ast_nodes: int = 12


class ConnascenceOfValueCheckConfig(LayerFilterConfig):
    severity: str = "warning"
    min_occurrences: int = 2
    ignored_values: list[str] = Field(default_factory=lambda: ["0", "1", ""])


class CustomExclusionRule(BaseModel):
    source_layer: str | None = None
    source_domain: str | None = None
    source_tag: str | None = None
    source_tags: list[str] | None = None
    source_meta: dict[str, Any] | None = None
    target_layer: str | None = None
    target_domain: str | None = None
    target_tag: str | None = None
    target_tags: list[str] | None = None
    target_meta: dict[str, Any] | None = None


class AllowedExceptionRule(BaseModel):
    model: str
    dependency: str


class CustomExclusionsCheckConfig(LayerFilterConfig):
    exclusions: list[CustomExclusionRule] = Field(default_factory=list)
    allowed_exceptions: list[AllowedExceptionRule] = Field(default_factory=list)


class ColumnParityMember(BaseModel):
    file: str
    substitutions: dict[str, str] = Field(default_factory=dict)

    @field_validator("file", mode="before")
    @classmethod
    def validate_file(cls, v: Any) -> str:
        return str(v)


class ColumnParityGroup(BaseModel):
    models_dir: str = ""
    reference: str
    members: list[ColumnParityMember] = Field(default_factory=list)
    exclude_columns: list[str] = Field(default_factory=list)
    reference_substitutions: dict[str, str] = Field(default_factory=dict)

    @field_validator("members", mode="before")
    @classmethod
    def validate_members(cls, v: Any) -> Any:
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, str):
                    result.append({"file": item})
                else:
                    result.append(item)
            return result
        return v


class DimensionParityTarget(BaseModel):
    file: str
    exclude_columns: list[str] = Field(default_factory=list)


class DimensionParityGroup(BaseModel):
    models_dir: str = ""
    left: DimensionParityTarget
    right: DimensionParityTarget

    @field_validator("left", "right", mode="before")
    @classmethod
    def validate_target(cls, v: Any) -> Any:
        if isinstance(v, str):
            return {"file": v}
        return v


class ContractGroupsConfig(BaseModel):
    column_parity_groups: list[ColumnParityGroup] = Field(default_factory=list)
    dimension_parity_groups: list[DimensionParityGroup] = Field(default_factory=list)


class SchemaContractsCheckConfig(LayerFilterConfig):
    column_parity_groups: list[ColumnParityGroup] = Field(default_factory=list)
    dimension_parity_groups: list[DimensionParityGroup] = Field(default_factory=list)


class ChecksConfig(BaseModel):
    layer_integrity: CheckEnabled = Field(default_factory=CheckEnabled)
    custom_exclusions: CustomExclusionsCheckConfig = Field(
        default_factory=CustomExclusionsCheckConfig
    )
    schema_contracts: SchemaContractsCheckConfig = Field(
        default_factory=SchemaContractsCheckConfig
    )
    dependency_graph: DependencyGraphCheckConfig = Field(
        default_factory=DependencyGraphCheckConfig
    )
    materialization_depth: MaterializationDepthCheckConfig = Field(
        default_factory=MaterializationDepthCheckConfig
    )
    duplicate_ctes: DuplicateCtesCheckConfig = Field(
        default_factory=DuplicateCtesCheckConfig
    )
    connascence_of_value: ConnascenceOfValueCheckConfig = Field(
        default_factory=ConnascenceOfValueCheckConfig
    )




class ClassificationMacrosRuleConfig(LayerFilterConfig):
    skip_layers: list[str] = Field(default_factory=lambda: ["sources"])
    columns: dict[str, str] = Field(
        default_factory=lambda: {
            "product_type": r"@product_type\b|@PRODUCT_TYPE\b",
            "billing_segment": r"@BILLING_SEGMENT\b|@billing_segment\b",
            "industry": r"@INDUSTRY\b|@industry\b",
        }
    )


class SqlComplexityRuleConfig(LayerFilterConfig):
    warn_only: bool = True
    thresholds: dict[str, list[int]] = Field(
        default_factory=lambda: {
            "decision_points": [15, 25],
            "cte_count": [8, 12],
            "join_count": [8, 12],
            "line_count": [250, 400],
        }
    )


class MartNamingRuleConfig(LayerFilterConfig):
    layer_name: str = "marts"
    rule: str = "prefix_with_subdirectory"


class ColumnNamesRuleConfig(LayerFilterConfig):
    replacements: dict[str, str] = Field(default_factory=dict)


class ColumnTypeRuleEntry(BaseModel):
    name: str
    pattern: str
    data_type: str


class ColumnTypesRuleConfig(LayerFilterConfig):
    rules: list[ColumnTypeRuleEntry] = Field(default_factory=list)
    equivalent_types: dict[str, list[str]] = Field(
        default_factory=lambda: {"text": ["text", "varchar"]}
    )


class MetadataRuleConfig(LayerFilterConfig):
    owner: bool = True
    description: bool = True
    grain: bool = True
    not_null: bool = True
    unique_values: bool = True


class FilenameEqualsModelnameRuleConfig(LayerFilterConfig):
    pass


class BanSelectStarRuleConfig(LayerFilterConfig):
    skip_layers: list[str] = Field(default_factory=lambda: ["sources"])


class NoPositionalGroupByOrOrderByRuleConfig(LayerFilterConfig):
    skip_layers: list[str] = Field(default_factory=lambda: ["sources"])


class EnvironmentAgnosticReferencesRuleConfig(LayerFilterConfig):
    banned_environments: list[str] = Field(
        default_factory=lambda: ["prod", "dev", "staging", "uat", "qa"]
    )


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
    ban_select_star: BanSelectStarRuleConfig = Field(
        default_factory=BanSelectStarRuleConfig
    )
    no_positional_group_by_or_order_by: NoPositionalGroupByOrOrderByRuleConfig = Field(
        default_factory=NoPositionalGroupByOrOrderByRuleConfig
    )
    environment_agnostic_references: EnvironmentAgnosticReferencesRuleConfig = Field(
        default_factory=EnvironmentAgnosticReferencesRuleConfig
    )


class FitnessFunctionsConfig(BaseModel):
    _project_root: Path = PrivateAttr(default_factory=Path.cwd)
    _config_file_found: bool = PrivateAttr(default=True)
    contract_groups_path: str = "linter_contract_groups.json"
    exclusions_path: str = "linter_exclusions.json"
    layers: LayersConfig = Field(default_factory=LayersConfig)
    checks: ChecksConfig = Field(default_factory=ChecksConfig)
    rules: RulesConfig = Field(default_factory=RulesConfig)
    contract_groups: ContractGroupsConfig | None = None
    exclusions: list[CustomExclusionRule] | None = None
    allowed_exceptions: list[AllowedExceptionRule] | None = None

    @property
    def config_file_found(self) -> bool:
        return self._config_file_found


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
    config_found = False

    if config_path is not None:
        yaml_path = Path(config_path)
        if not yaml_path.is_absolute():
            yaml_path = project_root / yaml_path
        if yaml_path.exists():
            config_found = True
            loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"Expected mapping in {yaml_path}")
            data = loaded

    if overrides:
        data = _deep_merge(data, overrides)

    config = FitnessFunctionsConfig.model_validate(data)
    config._project_root = project_root
    config._config_file_found = config_found
    return config


def init_fitness_config(
    project_root: Path,
    filename: str = "fitness_functions.yaml",
    force: bool = False,
) -> Path:
    """Scaffold an annotated starter fitness_functions.yaml configuration file."""
    target = project_root / filename
    if target.exists() and not force:
        raise FileExistsError(
            f"'{target.name}' already exists in {project_root}. Use --force to overwrite."
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(STARTER_CONFIG_YAML, encoding="utf-8")
    return target


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
