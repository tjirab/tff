"""Centralized, declarative CheckRegistry for fitness checks and rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Literal

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding, Severity
    from tff.core.rules.base import Rule

Scope = Literal["model", "dag"]


def normalize_check_name(name: str) -> str:
    """Normalize a check name/alias for case-insensitive and separator-agnostic lookups."""
    return name.lower().replace("-", "").replace("_", "").replace(" ", "")


def run_model_rule(
    rule_cls: type[Rule],
    models: dict[str, ModelRepresentation],
    severity: Severity = "error",
    check_name: str | None = None,
    config: FitnessFunctionsConfig | None = None,
) -> list[LintFinding]:
    """Execute a single model-level Rule across all eligible models in a project."""
    from tff.core.report import LintFinding
    from tff.core.utils.paths import model_path_relative

    rule = rule_cls(config=config)
    findings: list[LintFinding] = []
    finding_check = check_name or getattr(rule, "name", rule_cls.__name__.lower())

    for model in models.values():
        if model.is_external or model.is_symbolic:
            continue

        violation = rule.check_model(model)
        if violation:
            msgs = violation.violation_msg
            if isinstance(msgs, str):
                msgs = [msgs]
            for msg in msgs:
                model_label = f"{model.name}: "
                clean_msg = msg.removeprefix(model_label)
                findings.append(
                    LintFinding(
                        check=finding_check,
                        severity=severity,
                        model=model.name,
                        path=model_path_relative(model),
                        message=clean_msg,
                    )
                )
    return findings


@dataclass(frozen=True)
class CheckDefinition:
    """Metadata and execution specification for a single fitness check or rule."""

    id: str
    label: str
    category: str
    scope: Scope
    default_severity: Severity = "error"
    aliases: tuple[str, ...] = ()
    finding_check_id: str | None = None
    rule_cls: type[Rule] | None = None
    rule_module: str | None = None
    rule_class_name: str | None = None
    collector_fn: (
        Callable[[dict[str, ModelRepresentation], FitnessFunctionsConfig], list[LintFinding]]
        | None
    ) = None
    collector_module: str | None = None
    collector_func_name: str | None = None
    is_enabled_fn: Callable[[FitnessFunctionsConfig, str], bool] | None = None

    @property
    def canonical_id(self) -> str:
        return self.id

    @property
    def finding_id(self) -> str:
        return self.finding_check_id or (self.aliases[0] if self.aliases else self.id)

    def get_rule_cls(self) -> type[Rule] | None:
        if self.rule_cls is not None:
            return self.rule_cls
        if self.rule_module and self.rule_class_name:
            import importlib

            mod = importlib.import_module(self.rule_module)
            return getattr(mod, self.rule_class_name)
        return None

    def get_collector_fn(self) -> Callable | None:
        if self.collector_fn is not None:
            return self.collector_fn
        if self.collector_module and self.collector_func_name:
            import importlib

            mod = importlib.import_module(self.collector_module)
            return getattr(mod, self.collector_func_name)
        return None

    def is_enabled(self, config: FitnessFunctionsConfig, provider: str = "dbt") -> bool:
        if self.is_enabled_fn is not None:
            return self.is_enabled_fn(config, provider)
        return True

    def run(
        self,
        models: dict[str, ModelRepresentation],
        config: FitnessFunctionsConfig,
    ) -> list[LintFinding]:
        if self.scope == "model":
            rule_cls = self.get_rule_cls()
            if rule_cls is not None:
                return run_model_rule(
                    rule_cls,
                    models,
                    severity=self.default_severity,
                    check_name=self.finding_id,
                    config=config,
                )
            return []
        elif self.scope == "dag":
            collector = self.get_collector_fn()
            if collector is not None:
                return collector(models, config)
            return []
        return []


class CheckRegistry:
    """Registry holding definitions of all fitness checks and rules."""

    def __init__(self) -> None:
        self._checks: dict[str, CheckDefinition] = {}
        self._lookup: dict[str, CheckDefinition] = {}

    def register(self, check: CheckDefinition) -> None:
        self._checks[check.id] = check
        self._lookup[normalize_check_name(check.id)] = check
        if check.finding_check_id:
            self._lookup[normalize_check_name(check.finding_check_id)] = check
        for alias in check.aliases:
            self._lookup[normalize_check_name(alias)] = check

    def get(self, name_or_alias: str) -> CheckDefinition | None:
        return self._lookup.get(normalize_check_name(name_or_alias))

    def get_or_raise(self, name_or_alias: str) -> CheckDefinition:
        check = self.get(name_or_alias)
        if check is None:
            available = sorted(self._checks.keys())
            raise ValueError(
                f"Unknown check or rule: '{name_or_alias}'. "
                f"Available checks: {', '.join(available)}"
            )
        return check

    def all_checks(self) -> list[CheckDefinition]:
        return list(self._checks.values())

    def model_rules(self) -> list[CheckDefinition]:
        return [
            c
            for c in self._checks.values()
            if c.scope == "model" and (c.rule_cls is not None or c.rule_module is not None)
        ]

    def dag_checks(self) -> list[CheckDefinition]:
        return [c for c in self._checks.values() if c.scope == "dag"]

    def is_check_enabled(
        self,
        config: FitnessFunctionsConfig,
        check_name: str,
        provider: str = "dbt",
    ) -> bool:
        check = self.get(check_name)
        if check is None:
            return False
        return check.is_enabled(config, provider)

    def resolve_checks(
        self,
        checks: list[str] | None,
        config: FitnessFunctionsConfig,
        provider: str = "dbt",
    ) -> list[CheckDefinition]:
        if checks is None:
            return [c for c in self.all_checks() if c.is_enabled(config, provider)]

        resolved: list[CheckDefinition] = []
        seen: set[str] = set()

        for name in checks:
            norm = normalize_check_name(name)
            if norm == "rules":
                for rule_def in self.model_rules():
                    if rule_def.id not in seen:
                        seen.add(rule_def.id)
                        resolved.append(rule_def)
            elif norm == "sqlmesh":
                # Container key for SQLMesh linter
                continue
            else:
                check_def = self.get(name)
                if check_def is not None:
                    if check_def.id not in seen:
                        seen.add(check_def.id)
                        resolved.append(check_def)
                else:
                    self.get_or_raise(name)

        return resolved

    def run_checks(
        self,
        models: dict[str, ModelRepresentation],
        config: FitnessFunctionsConfig,
        checks: list[str] | None = None,
        provider: str = "dbt",
    ) -> tuple[list[LintFinding], list[str]]:
        resolved = self.resolve_checks(checks, config, provider=provider)
        findings: list[LintFinding] = []
        for check_def in resolved:
            findings.extend(check_def.run(models, config))

        if checks is not None:
            executed_names = checks
        else:
            executed_names = ["rules"] + [
                c.finding_id for c in resolved if c.scope == "dag"
            ]

        return findings, executed_names

    def get_check_labels(self) -> dict[str, str]:
        labels: dict[str, str] = {}
        for c in self.all_checks():
            labels[c.id] = c.label
            if c.finding_check_id:
                labels[c.finding_check_id] = c.label
            for alias in c.aliases:
                labels[alias] = c.label
        return labels

    def get_connascence_categories(self) -> dict[str, str]:
        cats: dict[str, str] = {}
        for c in self.all_checks():
            cats[c.id] = c.category
            if c.finding_check_id:
                cats[c.finding_check_id] = c.category
            for alias in c.aliases:
                cats[alias] = c.category
        return cats

    def get_categories(self) -> dict[str, list[str]]:
        cats: dict[str, list[str]] = {
            "Connascence of Name (CoN)": [],
            "Connascence of Type (CoT)": [],
            "Connascence of Position (CoP)": [],
            "Connascence of Meaning (CoM)": [],
            "Connascence of Algorithm (CoA)": [],
            "Connascence of Value (CoV)": [],
            "Dynamic Coupling & DAG Structure": [],
            "Quality & Metadata (Non-Connascence)": [],
        }
        for c in self.all_checks():
            key = c.finding_id
            if c.category in cats and key not in cats[c.category]:
                cats[c.category].append(key)
        return cats

    def get_project_level_check_names(self) -> set[str]:
        return {
            "layer_integrity",
            "custom_exclusions",
            "schema_contracts",
            "dependency_graph",
            "materialization_depth",
        }

    def get_architectural_check_names(self) -> frozenset[str]:
        return frozenset(
            {
                "layer_integrity",
                "custom_exclusions",
                "schema_contracts",
                "dependency_graph",
                "duplicate_ctes",
                "connascence_of_value",
            }
        )


def create_default_registry() -> CheckRegistry:
    """Create and populate the default CheckRegistry with all TFF checks and rules."""
    reg = CheckRegistry()

    # 1. Connascence of Name (CoN)
    reg.register(
        CheckDefinition(
            id="ban_select_star",
            label="No SELECT *",
            category="Connascence of Name (CoN)",
            scope="model",
            aliases=("banselectstar",),
            finding_check_id="banselectstar",
            rule_module="tff.core.rules.ban_select_star",
            rule_class_name="BanSelectStar",
            is_enabled_fn=lambda cfg, p: bool(cfg.rules.ban_select_star.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="filename_equals_modelname",
            label="Filename equals model name",
            category="Connascence of Name (CoN)",
            scope="model",
            aliases=("filenameequalsmodelname",),
            finding_check_id="filenameequalsmodelname",
            rule_module="tff.core.rules.filename_equals_modelname",
            rule_class_name="FilenameEqualsModelname",
            is_enabled_fn=lambda cfg, p: bool(cfg.rules.filename_equals_modelname.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="column_names",
            label="Column names",
            category="Connascence of Name (CoN)",
            scope="model",
            aliases=("columnnames",),
            finding_check_id="columnnames",
            rule_module="tff.core.rules.column_names",
            rule_class_name="ColumnNames",
            is_enabled_fn=lambda cfg, p: bool(cfg.rules.column_names.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="mart_model_naming_convention",
            label="Mart naming convention",
            category="Connascence of Name (CoN)",
            scope="model",
            aliases=("martmodelnamingconvention", "mart_naming"),
            finding_check_id="martmodelnamingconvention",
            rule_module="tff.core.rules.mart_naming",
            rule_class_name="MartModelNamingConvention",
            is_enabled_fn=lambda cfg, p: bool(cfg.rules.mart_naming.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="ambiguous_or_invalid_column",
            label="Ambiguous/invalid column",
            category="Connascence of Name (CoN)",
            scope="model",
            aliases=("ambiguousorinvalidcolumn",),
            finding_check_id="ambiguousorinvalidcolumn",
            is_enabled_fn=lambda cfg, p: p == "sqlmesh",
        )
    )
    reg.register(
        CheckDefinition(
            id="invalid_select_star_expansion",
            label="Invalid SELECT * expansion",
            category="Connascence of Name (CoN)",
            scope="model",
            aliases=("invalidselectstarexpansion",),
            finding_check_id="invalidselectstarexpansion",
            is_enabled_fn=lambda cfg, p: p == "sqlmesh",
        )
    )

    # 2. Connascence of Type (CoT)
    reg.register(
        CheckDefinition(
            id="column_types",
            label="Column types",
            category="Connascence of Type (CoT)",
            scope="model",
            aliases=("columntypes",),
            finding_check_id="columntypes",
            rule_module="tff.core.rules.column_types",
            rule_class_name="ColumnTypes",
            is_enabled_fn=lambda cfg, p: bool(cfg.rules.column_types.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="schema_contracts",
            label="Schema contracts",
            category="Connascence of Type (CoT)",
            scope="dag",
            collector_module="tff.core.checks.schema_contracts",
            collector_func_name="collect_schema_contract_findings",
            collector_fn=lambda models, cfg: __import__(
                "tff.core.checks.schema_contracts", fromlist=["collect_schema_contract_findings"]
            ).collect_schema_contract_findings(models, cfg),
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.schema_contracts.enabled),
        )
    )

    # 3. Connascence of Position (CoP)
    reg.register(
        CheckDefinition(
            id="no_positional_group_by_or_order_by",
            label="No positional GROUP BY or ORDER BY",
            category="Connascence of Position (CoP)",
            scope="model",
            aliases=("nopositionalgroupbyororderby",),
            finding_check_id="nopositionalgroupbyororderby",
            rule_module="tff.core.rules.no_positional_group_by_or_order_by",
            rule_class_name="NoPositionalGroupByOrOrderBy",
            is_enabled_fn=lambda cfg, p: bool(
                cfg.rules.no_positional_group_by_or_order_by.enabled
            ),
        )
    )

    # 4. Connascence of Meaning (CoM)
    reg.register(
        CheckDefinition(
            id="classification_macros",
            label="Classification macros",
            category="Connascence of Meaning (CoM)",
            scope="model",
            aliases=("classificationmacros",),
            finding_check_id="classificationmacros",
            rule_module="tff.core.rules.classification_macros",
            rule_class_name="ClassificationMacros",
            is_enabled_fn=lambda cfg, p: bool(cfg.rules.classification_macros.enabled),
        )
    )

    # 5. Connascence of Algorithm (CoA)
    reg.register(
        CheckDefinition(
            id="duplicate_ctes",
            label="Duplicate CTEs",
            category="Connascence of Algorithm (CoA)",
            scope="dag",
            collector_module="tff.core.checks.duplicate_ctes",
            collector_func_name="collect_duplicate_cte_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.duplicate_ctes.enabled),
        )
    )

    # 6. Connascence of Value (CoV)
    reg.register(
        CheckDefinition(
            id="connascence_of_value",
            label="Connascence of Value",
            category="Connascence of Value (CoV)",
            scope="dag",
            collector_module="tff.core.checks.connascence_of_value",
            collector_func_name="collect_connascence_of_value_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.connascence_of_value.enabled),
        )
    )

    # 7. Dynamic Coupling & DAG Structure
    reg.register(
        CheckDefinition(
            id="layer_integrity",
            label="Layer integrity",
            category="Dynamic Coupling & DAG Structure",
            scope="dag",
            collector_module="tff.core.checks.layer_integrity",
            collector_func_name="collect_layer_integrity_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.layer_integrity.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="custom_exclusions",
            label="Custom exclusions",
            category="Dynamic Coupling & DAG Structure",
            scope="dag",
            collector_module="tff.core.checks.custom_exclusions",
            collector_func_name="collect_custom_exclusion_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.custom_exclusions.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="dependency_graph",
            label="Dependency graph",
            category="Dynamic Coupling & DAG Structure",
            scope="dag",
            collector_module="tff.core.checks.dependency_graph",
            collector_func_name="collect_dependency_graph_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.dependency_graph.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="materialization_depth",
            label="materialization_depth",
            category="Dynamic Coupling & DAG Structure",
            scope="dag",
            collector_module="tff.core.checks.materialization_depth",
            collector_func_name="collect_materialization_depth_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.materialization_depth.enabled),
        )
    )
    reg.register(
        CheckDefinition(
            id="environment_agnostic_references",
            label="Environment-agnostic references",
            category="Dynamic Coupling & DAG Structure",
            scope="model",
            aliases=("environmentagnosticreferences",),
            finding_check_id="environmentagnosticreferences",
            rule_module="tff.core.rules.environment_agnostic_references",
            rule_class_name="EnvironmentAgnosticReferences",
            is_enabled_fn=lambda cfg, p: bool(
                cfg.rules.environment_agnostic_references.enabled
            ),
        )
    )

    # 8. Quality & Metadata (Non-Connascence)
    reg.register(
        CheckDefinition(
            id="no_missing_owner",
            label="Missing owner",
            category="Quality & Metadata (Non-Connascence)",
            scope="model",
            aliases=("nomissingowner",),
            finding_check_id="nomissingowner",
            rule_module="tff.core.rules.metadata",
            rule_class_name="NoMissingOwner",
            is_enabled_fn=lambda cfg, p: bool(
                cfg.rules.metadata.enabled and cfg.rules.metadata.owner
            ),
        )
    )
    reg.register(
        CheckDefinition(
            id="no_missing_description",
            label="Missing description",
            category="Quality & Metadata (Non-Connascence)",
            scope="model",
            aliases=("nomissingdescription",),
            finding_check_id="nomissingdescription",
            rule_module="tff.core.rules.metadata",
            rule_class_name="NoMissingDescription",
            is_enabled_fn=lambda cfg, p: bool(
                cfg.rules.metadata.enabled and cfg.rules.metadata.description
            ),
        )
    )
    reg.register(
        CheckDefinition(
            id="no_missing_grain",
            label="Missing grain",
            category="Quality & Metadata (Non-Connascence)",
            scope="model",
            aliases=("nomissinggrain",),
            finding_check_id="nomissinggrain",
            rule_module="tff.core.rules.metadata",
            rule_class_name="NoMissingGrain",
            is_enabled_fn=lambda cfg, p: bool(
                cfg.rules.metadata.enabled and cfg.rules.metadata.grain
            ),
        )
    )
    reg.register(
        CheckDefinition(
            id="no_missing_not_null",
            label="Missing not_null audit",
            category="Quality & Metadata (Non-Connascence)",
            scope="model",
            aliases=("nomissingnotnull",),
            finding_check_id="nomissingnotnull",
            rule_module="tff.core.rules.metadata",
            rule_class_name="NoMissingNotNull",
            is_enabled_fn=lambda cfg, p: bool(
                cfg.rules.metadata.enabled and cfg.rules.metadata.not_null
            ),
        )
    )
    reg.register(
        CheckDefinition(
            id="no_missing_unique_values",
            label="Missing unique_values audit",
            category="Quality & Metadata (Non-Connascence)",
            scope="model",
            aliases=("nomissinguniquevalues",),
            finding_check_id="nomissinguniquevalues",
            rule_module="tff.core.rules.metadata",
            rule_class_name="NoMissingUniqueValues",
            is_enabled_fn=lambda cfg, p: bool(
                cfg.rules.metadata.enabled and cfg.rules.metadata.unique_values
            ),
        )
    )
    reg.register(
        CheckDefinition(
            id="no_missing_audits",
            label="Missing audits",
            category="Quality & Metadata (Non-Connascence)",
            scope="model",
            aliases=("nomissingaudits",),
            finding_check_id="nomissingaudits",
            is_enabled_fn=lambda cfg, p: False,
        )
    )
    reg.register(
        CheckDefinition(
            id="sql_complexity",
            label="SQL complexity",
            category="Quality & Metadata (Non-Connascence)",
            scope="model",
            aliases=("sqlcomplexity",),
            finding_check_id="sqlcomplexity",
            rule_module="tff.core.rules.sql_complexity",
            rule_class_name="SqlComplexity",
            is_enabled_fn=lambda cfg, p: bool(cfg.rules.sql_complexity.enabled),
        )
    )

    return reg


registry: CheckRegistry = create_default_registry()
