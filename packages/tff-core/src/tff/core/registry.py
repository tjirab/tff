"""Centralized, declarative CheckRegistry for fitness checks and rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Literal

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding, Severity
    from tff.core.rules.base import Rule

Scope = Literal["model", "dag"]


def normalize_check_name(name: str) -> str:
    """Normalize a check name/alias for case-insensitive and separator-agnostic lookups."""
    return name.lower().replace("-", "").replace("_", "").replace(" ", "")


def _extract_enabled(container: Any, norm_names: set[str]) -> bool | None:
    if container is None:
        return None
    entries = dict(getattr(container, "__dict__", {}))
    if hasattr(container, "model_extra") and container.model_extra:
        entries.update(container.model_extra)
    for k, val in entries.items():
        if normalize_check_name(k) in norm_names:
            if isinstance(val, bool):
                return val
            if isinstance(val, dict):
                return bool(val.get("enabled", True))
            if hasattr(val, "enabled"):
                return bool(val.enabled)
    return None


def is_rule_enabled_in_config(config: FitnessFunctionsConfig, *names: str) -> bool:
    """Check whether a check or rule is enabled in config.rules or config.checks."""
    norm_names = {normalize_check_name(n) for n in names if n}
    if not norm_names:
        return True

    res = _extract_enabled(getattr(config, "rules", None), norm_names)
    if res is not None:
        return res

    res_checks = _extract_enabled(getattr(config, "checks", None), norm_names)
    if res_checks is not None:
        return res_checks

    return True




def run_model_rule(
    rule_cls: type[Rule],
    models: dict[str, ModelRepresentation],
    severity: Severity = "error",
    check_name: str | None = None,
    config: FitnessFunctionsConfig | None = None,
    max_workers: int | None = None,
    chunk_size: int | None = None,
) -> list[LintFinding]:
    """Execute a single model-level Rule across all eligible models in a project."""
    from tff.core.parallel import run_parallel_model_rule

    return run_parallel_model_rule(
        rule_cls=rule_cls,
        models=list(models.values()),
        severity=severity,
        check_name=check_name,
        config=config,
        max_workers=max_workers,
        chunk_size=chunk_size,
    )


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
    maturity: str = "stable"
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
    docs_url: str | None = None
    description: str = ""
    why_it_matters: str = ""
    how_to_fix: str = ""
    configuration_example: str = ""
    providers: tuple[str, ...] = ("dbt", "sqlmesh", "dataform")
    is_fixable: bool = False

    @property
    def what_it_checks(self) -> str:
        return self.description

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

    def get_severity(self, config: FitnessFunctionsConfig | None = None) -> Severity:
        """Resolve severity from configuration override or fall back to default_severity."""
        if config is not None:
            candidates = [self.id, self.finding_id, *self.aliases]
            norm_candidates = {normalize_check_name(c) for c in candidates if c}
            for section_name in ("rules", "checks"):
                cfg_section = getattr(config, section_name, None)
                if cfg_section is not None:
                    entries = dict(getattr(cfg_section, "__dict__", {}))
                    if hasattr(cfg_section, "model_extra") and cfg_section.model_extra:
                        entries.update(cfg_section.model_extra)
                    for attr, val in entries.items():
                        if normalize_check_name(attr) in norm_candidates:
                            sev = getattr(val, "severity", None) if not isinstance(val, dict) else val.get("severity")
                            if sev and str(sev).lower() in ("error", "warning"):
                                return str(sev).lower()  # type: ignore[return-value]

        return self.default_severity

    def is_enabled(self, config: FitnessFunctionsConfig, provider: str = "dbt") -> bool:
        if self.is_enabled_fn is not None:
            return self.is_enabled_fn(config, provider)
        return is_rule_enabled_in_config(config, self.id, self.finding_id, *self.aliases)

    def run(
        self,
        models: dict[str, ModelRepresentation],
        config: FitnessFunctionsConfig,
        max_workers: int | None = None,
        chunk_size: int | None = None,
    ) -> list[LintFinding]:
        if self.scope == "model":
            rule_cls = self.get_rule_cls()
            if rule_cls is not None:
                severity = self.get_severity(config)
                return run_model_rule(
                    rule_cls,
                    models,
                    severity=severity,
                    check_name=self.finding_id,
                    config=config,
                    max_workers=max_workers,
                    chunk_size=chunk_size,
                )
            return []
        elif self.scope == "dag":
            collector = self.get_collector_fn()
            if collector is not None:
                import inspect

                sig = inspect.signature(collector)
                if "max_workers" in sig.parameters:
                    return collector(models, config, max_workers=max_workers)
                return collector(models, config)
            return []
        return []



class CheckRegistry:
    """Registry holding definitions of all fitness checks and rules."""

    def __init__(self) -> None:
        self._checks: dict[str, CheckDefinition] = {}
        self._lookup: dict[str, CheckDefinition] = {}
        self._loaded_plugins: set[str] = set()

    def register(self, check: CheckDefinition) -> None:
        self._checks[check.id] = check
        self._lookup[normalize_check_name(check.id)] = check
        if check.finding_check_id:
            self._lookup[normalize_check_name(check.finding_check_id)] = check
        for alias in check.aliases:
            self._lookup[normalize_check_name(alias)] = check

    def register_rule(
        self,
        rule_cls: type[Rule],
        id: str | None = None,
        label: str | None = None,
        category: str = "Custom Rules",
        default_severity: Severity = "error",
        aliases: tuple[str, ...] = (),
        finding_check_id: str | None = None,
        is_enabled_fn: Callable[[FitnessFunctionsConfig, str], bool] | None = None,
        docs_url: str | None = None,
        description: str = "",
        why_it_matters: str = "",
        how_to_fix: str = "",
        configuration_example: str = "",
        providers: tuple[str, ...] = ("dbt", "sqlmesh", "dataform"),
        is_fixable: bool = False,
    ) -> CheckDefinition:
        """Convenience method to register a model-level Rule class."""
        rule_id = (
            id
            or getattr(rule_cls, "rule_id", None)
            or getattr(rule_cls, "name", None)
            or rule_cls.__name__.lower()
        )
        rule_label = (
            label
            or getattr(rule_cls, "label", None)
            or (rule_cls.__doc__.strip().splitlines()[0] if rule_cls.__doc__ else rule_id)
        )
        rule_category = getattr(rule_cls, "category", category)
        rule_severity = getattr(
            rule_cls,
            "default_severity",
            getattr(rule_cls, "severity", default_severity),
        )
        rule_aliases = getattr(rule_cls, "aliases", aliases)
        rule_finding_id = (
            finding_check_id
            or getattr(rule_cls, "finding_check_id", None)
            or getattr(rule_cls, "name", None)
            or rule_id
        )
        rule_maturity = getattr(rule_cls, "maturity", "stable")
        rule_docs_url = (
            docs_url
            or getattr(rule_cls, "docs_url", None)
            or getattr(rule_cls, "help_url", None)
        )
        rule_description = (
            description
            or getattr(rule_cls, "description", None)
            or (rule_cls.__doc__.strip() if rule_cls.__doc__ else "")
        )
        rule_why = why_it_matters or getattr(rule_cls, "why_it_matters", "")
        rule_how = how_to_fix or getattr(rule_cls, "how_to_fix", "")
        rule_config = configuration_example or getattr(rule_cls, "configuration_example", "")
        rule_providers = getattr(rule_cls, "providers", providers)
        rule_fixable = getattr(rule_cls, "is_fixable", is_fixable)

        check_def = CheckDefinition(
            id=rule_id,
            label=rule_label,
            category=rule_category,
            scope="model",
            default_severity=rule_severity,
            aliases=tuple(rule_aliases),
            finding_check_id=rule_finding_id,
            maturity=rule_maturity,
            rule_cls=rule_cls,
            is_enabled_fn=is_enabled_fn,
            docs_url=rule_docs_url,
            description=rule_description,
            why_it_matters=rule_why,
            how_to_fix=rule_how,
            configuration_example=rule_config,
            providers=rule_providers,
            is_fixable=rule_fixable,
        )
        self.register(check_def)
        return check_def

    def unregister(self, check_id: str) -> None:
        """Unregister a check or rule by id or finding_check_id."""
        check = self._checks.pop(check_id, None)
        if check is not None:
            self._lookup.pop(normalize_check_name(check.id), None)
            if check.finding_check_id:
                self._lookup.pop(normalize_check_name(check.finding_check_id), None)
            for alias in check.aliases:
                self._lookup.pop(normalize_check_name(alias), None)

    def load_entry_points(self) -> list[CheckDefinition]:
        """Discover and register rules from 'tff.rules' entry points."""
        from tff.core.plugins import discover_rule_entry_points

        return discover_rule_entry_points(registry=self)

    def load_plugins(
        self,
        plugins: list[str | Path],
        project_root: Path | None = None,
    ) -> list[CheckDefinition]:
        """Load external rule/adapter plugins from file paths or module names."""
        from tff.core.plugins import load_plugins

        return load_plugins(plugins, project_root=project_root, registry=self)


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

    def get_by_category(self, query: str) -> list[CheckDefinition]:
        """Find all checks matching a category name or abbreviation (e.g. CoA, CoV, CoN, CoT, CoP, CoM, DAG)."""
        norm = normalize_check_name(query)
        abbr_map = {
            "con": "Connascence of Name (CoN)",
            "cot": "Connascence of Type (CoT)",
            "cop": "Connascence of Position (CoP)",
            "com": "Connascence of Meaning (CoM)",
            "coa": "Connascence of Algorithm (CoA)",
            "cov": "Connascence of Value (CoV)",
            "dag": "Dynamic Coupling & DAG Structure",
            "coupling": "Dynamic Coupling & DAG Structure",
            "dynamiccoupling": "Dynamic Coupling & DAG Structure",
            "quality": "Quality & Metadata (Non-Connascence)",
            "metadata": "Quality & Metadata (Non-Connascence)",
        }
        target_cat = abbr_map.get(norm)
        if target_cat:
            return [c for c in self.all_checks() if c.category == target_cat]

        results: list[CheckDefinition] = []
        for check in self.all_checks():
            cat_norm = normalize_check_name(check.category)
            if norm and (norm == cat_norm or norm in cat_norm):
                results.append(check)
        return results

    def get_docs_url(self, name_or_alias: str) -> str | None:
        """Resolve documentation URL for a check or rule name/alias."""
        check = self.get(name_or_alias)
        if check is not None:
            return check.docs_url
        return None

    def get_docs_urls(self) -> dict[str, str]:
        """Return a mapping of check IDs, finding IDs, and aliases to their documentation URLs."""
        urls: dict[str, str] = {}
        for c in self.all_checks():
            if c.docs_url:
                urls[c.id] = c.docs_url
                if c.finding_check_id:
                    urls[c.finding_check_id] = c.docs_url
                for alias in c.aliases:
                    urls[alias] = c.docs_url
        return urls

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
        max_workers: int | None = None,
    ) -> tuple[list[LintFinding], list[str]]:
        from tff.core.parallel import get_max_workers

        workers = get_max_workers(config=config, override=max_workers)
        resolved = self.resolve_checks(checks, config, provider=provider)
        logger.debug(
            "Executing %d check(s) across %d model(s) (workers=%d): %s",
            len(resolved),
            len(models),
            workers,
            [c.id for c in resolved],
        )
        findings: list[LintFinding] = []

        if workers <= 1 or len(resolved) <= 1:
            for check_def in resolved:
                logger.debug("Executing check '%s' (scope=%s, category=%s)", check_def.id, check_def.scope, check_def.category)
                try:
                    res = check_def.run(models, config, max_workers=workers)
                    logger.debug("Check '%s' produced %d finding(s)", check_def.id, len(res))
                    findings.extend(res)
                except Exception as exc:
                    logger.warning("Check '%s' failed to execute: %s", check_def.id, exc, exc_info=True)
                    err_msg = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
                    from tff.core.report import LintFinding

                    findings.append(
                        LintFinding(
                            check="rule_execution_error",
                            severity="error",
                            model="project",
                            path="project",
                            message=f"Check '{check_def.id}' failed to execute: {err_msg}",
                        )
                    )
        else:
            from concurrent.futures import ThreadPoolExecutor

            pool_size = min(workers, len(resolved))
            with ThreadPoolExecutor(max_workers=pool_size) as executor:
                def _run_single(c: CheckDefinition) -> list[LintFinding]:
                    logger.debug("Executing check '%s' (scope=%s, category=%s)", c.id, c.scope, c.category)
                    try:
                        res = c.run(models, config, max_workers=1)
                        logger.debug("Check '%s' produced %d finding(s)", c.id, len(res))
                        return res
                    except Exception as exc:
                        logger.warning("Check '%s' failed to execute: %s", c.id, exc, exc_info=True)
                        err_msg = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__
                        from tff.core.report import LintFinding

                        return [
                            LintFinding(
                                check="rule_execution_error",
                                severity="error",
                                model="project",
                                path="project",
                                message=f"Check '{c.id}' failed to execute: {err_msg}",
                            )
                        ]

                results = executor.map(_run_single, resolved)
                for res in results:
                    findings.extend(res)

        if checks is not None:
            executed_names = checks
        else:
            executed_names = ["rules"] + [
                c.finding_id for c in resolved if c.scope == "dag"
            ]

        return findings, executed_names

    def get_check_labels(self) -> dict[str, str]:
        labels: dict[str, str] = {
            "rule_execution_error": "Rule execution error",
        }
        for c in self.all_checks():
            labels[c.id] = c.label
            if c.finding_check_id:
                labels[c.finding_check_id] = c.label
            for alias in c.aliases:
                labels[alias] = c.label
        return labels

    def get_connascence_categories(self) -> dict[str, str]:
        cats: dict[str, str] = {
            "rule_execution_error": "Execution Errors",
        }
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
            "Execution Errors": ["rule_execution_error"],
        }
        for c in self.all_checks():
            key = c.finding_id
            if c.category not in cats:
                cats[c.category] = []
            if key not in cats[c.category]:
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
                "join_type_parity",
            }
        )


def create_default_registry() -> CheckRegistry:
    """Create and populate the default CheckRegistry with all tff checks and rules."""
    reg = CheckRegistry()
    docs_base = "https://tff.readthedocs.io/en/latest/rules_and_checks/#"

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
            docs_url=f"{docs_base}ban-select-ban_select_star",
            description="Disallows wildcard SELECT * statements in model queries. Requires explicit column naming to reduce model coupling. Aggregate expressions (e.g. COUNT(*)) are permitted.",
            why_it_matters="Using wildcard SELECT * creates implicit coupling (Connascence of Name) between models. Upstream schema changes or column additions propagate unexpectedly downstream, breaking contracts, invalidating views, or altering model schemas.",
            how_to_fix="Explicitly list the required columns in the SELECT clause instead of using *.",
            configuration_example="rules:\n  ban_select_star:\n    enabled: true\n    skip_layers: [sources]",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}filename-equals-model-name-filename_equals_modelname",
            description="Validates that the model's catalog identifier matches the stem of its source SQL file on disk.",
            why_it_matters="Discrepancies between the file name and model name make models hard to locate, break developer expectations, and create confusion when navigating repositories.",
            how_to_fix="Rename the SQL file to match the model name or update the model configuration name to match the file stem.",
            configuration_example="rules:\n  filename_equals_modelname:\n    enabled: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}column-names-column_names",
            description="Enforces naming standards on columns by checking for deprecated names, forbidden substrings, or inconsistent column patterns.",
            why_it_matters="Inconsistent column naming causes Connascence of Name across transformation pipelines, forcing downstream models and consumers to memorize variations of the same business attribute.",
            how_to_fix="Rename deprecated columns to the canonical replacement specified in the rule configuration.",
            configuration_example="rules:\n  column_names:\n    enabled: true\n    replacements:\n      api_request: api_call\n      cust_id: customer_id",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}mart-naming-mart_naming",
            description="Enforces naming conventions for models residing inside subfolders of the marts layer directory (e.g. marts/marketing/ad_performance.sql should be named marketing_ad_performance.sql).",
            why_it_matters="Ensures model names remain globally unique and immediately convey their domain ownership even when referenced without folder paths.",
            how_to_fix="Prefix the model file name with the name of its enclosing subdirectory (e.g. rename ad_performance.sql to marketing_ad_performance.sql).",
            configuration_example="rules:\n  mart_naming:\n    enabled: true\n    layer_name: marts\n    rule: prefix_with_subdirectory",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url="https://tff.readthedocs.io/en/latest/rules_and_checks/",
            description="Flags ambiguous column references or invalid column resolutions in SQL queries using SQLMesh semantic analysis.",
            why_it_matters="Ambiguous column references make queries brittle and can cause runtime syntax or semantic errors when schemas evolve.",
            how_to_fix="Disambiguate column references by qualifying them with table or CTE aliases.",
            configuration_example="checks:\n  ambiguous_or_invalid_column:\n    enabled: true",
            providers=("sqlmesh",),
            is_fixable=False,
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
            docs_url="https://tff.readthedocs.io/en/latest/rules_and_checks/",
            description="Flags invalid wildcard expansions or column projections that cannot be resolved against upstream model schemas.",
            why_it_matters="Unresolvable SELECT * projections indicate missing upstream columns or broken lineage contracts.",
            how_to_fix="Explicitly specify valid projected columns or resolve upstream schema definitions.",
            configuration_example="checks:\n  invalid_select_star_expansion:\n    enabled: true",
            providers=("sqlmesh",),
            is_fixable=False,
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
            docs_url=f"{docs_base}column-types-column_types",
            description="Ensures columns matching specific name patterns are defined with expected data types (e.g. columns ending in _id must be typed as text).",
            why_it_matters="Type mismatches for the same conceptual attribute across models introduce Connascence of Type, risking join failures or expensive implicit type conversions.",
            how_to_fix="Cast or define the column to match the expected data type family configured for that column pattern.",
            configuration_example="rules:\n  column_types:\n    enabled: true\n    rules:\n      - name: id_is_text\n        pattern: '_id$'\n        data_type: text\n    equivalent_types:\n      text: [text, varchar]",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}schema-contracts-schema_contracts",
            description="Enforces structural schema parity between related models (column parity groups and dimension parity groups).",
            why_it_matters="Models representing parallel replicas or shared dimensions must stay strictly synchronized to prevent schema drift.",
            how_to_fix="Align member model columns with the reference model schema, or declare explicit substitution mappings / exclusions.",
            configuration_example="contract_groups:\n  column_parity_groups:\n    - reference: models/core/dim_customer_ref.sql\n      exclude_columns: [created_at, updated_at]\n      members:\n        - models/core/dim_customer_replica.sql\nchecks:\n  schema_contracts:\n    enabled: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
        )
    )
    reg.register(
        CheckDefinition(
            id="join_type_parity",
            label="Join type parity",
            category="Connascence of Type (CoT)",
            scope="dag",
            aliases=("jointypeparity", "type_parity", "join_types", "joined_column_types"),
            finding_check_id="join_type_parity",
            collector_module="tff.core.checks.join_type_parity",
            collector_func_name="collect_join_type_parity_findings",
            collector_fn=lambda models, cfg: __import__(
                "tff.core.checks.join_type_parity",
                fromlist=["collect_join_type_parity_findings"],
            ).collect_join_type_parity_findings(models, cfg),
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.join_type_parity.enabled),
            docs_url=f"{docs_base}join-type-parity-join_type_parity",
            description="Validates data type parity for joined columns across SQL queries to eliminate Connascence of Type (CoT).",
            why_it_matters="Joining columns with mismatching data types (e.g. VARCHAR joined to INT) causes dynamic casting overhead, disables index/partition pruning, or causes query failures.",
            how_to_fix="Cast joined columns to a compatible type family in upstream staging models, or add an explicit CAST at the join condition.",
            configuration_example="checks:\n  join_type_parity:\n    enabled: true\n    severity: error\n    skip_layers: [staging]",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}no-positional-group-byorder-by-no_positional_group_by_or_order_by-auto-fixable",
            description="Prevents using ordinal integers (e.g. GROUP BY 1, 2 or ORDER BY 1 DESC) instead of explicit column name references.",
            why_it_matters="Positional grouping introduces Connascence of Position (CoP). Modifying the SELECT list order unintentionally alters grouping and sorting semantics without syntax errors.",
            how_to_fix="Replace positional integers with explicit column names or aliases, or run 'tff lint --fix' to rewrite them automatically.",
            configuration_example="rules:\n  no_positional_group_by_or_order_by:\n    enabled: true\n    skip_layers: [sources]",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=True,
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
            docs_url=f"{docs_base}classification-macros-classification_macros",
            description="Enforces Connascence of Meaning (CoM) by requiring classification columns to use standard macros instead of inline CASE statements.",
            why_it_matters="When business classification logic (such as customer status or tier) is repeated as inline CASE statements, logic updates across models become error-prone and drift apart.",
            how_to_fix="Replace inline CASE statements with the designated project macro (e.g. {{ is_premium_tier('status') }}).",
            configuration_example="rules:\n  classification_macros:\n    enabled: true\n    columns:\n      product_type: '@product_type\\b'",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
        )
    )

    # 5. Connascence of Algorithm (CoA)
    reg.register(
        CheckDefinition(
            id="duplicate_ctes",
            label="Duplicate CTEs",
            category="Connascence of Algorithm (CoA)",
            scope="dag",
            default_severity="warning",
            collector_module="tff.core.checks.duplicate_ctes",
            collector_func_name="collect_duplicate_cte_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.duplicate_ctes.enabled),
            docs_url=f"{docs_base}duplicate-ctes-duplicate_ctes",
            description="Detects duplicate or near-identical Common Table Expressions (CTEs) across different SQL models using normalized AST subtree hashing.",
            why_it_matters="When transformation algorithms are duplicated across models, any future change to the business logic requires finding and updating every copy in sync. If one copy is missed, data warehouse divergence occurs silently.",
            how_to_fix="1. Lift the duplicate CTE into a shared upstream model (e.g. models/intermediate/int_users_cleaned.sql).\n2. Reference the shared model downstream using ref('int_users_cleaned').",
            configuration_example="checks:\n  duplicate_ctes:\n    enabled: true\n    min_lines: 4\n    severity: warning",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
        )
    )

    # 6. Connascence of Value (CoV)
    reg.register(
        CheckDefinition(
            id="connascence_of_value",
            label="Connascence of Value",
            category="Connascence of Value (CoV)",
            scope="dag",
            default_severity="warning",
            collector_module="tff.core.checks.connascence_of_value",
            collector_func_name="collect_connascence_of_value_findings",
            is_enabled_fn=lambda cfg, p: bool(cfg.checks.connascence_of_value.enabled),
            docs_url=f"{docs_base}connascence-of-value-connascence_of_value",
            description="Identifies Connascence of Value (CoV) by flagging business literal values (strings, numbers) duplicated across multiple models.",
            why_it_matters="When multiple models share hardcoded business constants, changing the value in one place requires synchronized updates across all models, leading to silent discrepancies if any are missed.",
            how_to_fix="1. Evaluate the value in an upstream staging model and expose a boolean flag.\n2. Encapsulate into a macro or project variable.\n3. Create a seed mapping table for multi-attribute lookups.",
            configuration_example="checks:\n  connascence_of_value:\n    enabled: true\n    min_occurrences: 2\n    ignored_values: ['0', '1', '']",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}layer-integrity-layer_integrity",
            description="Enforces unidirectional dependency flow between layers (upstream cannot depend on downstream) and mart domain isolation (marts domains cannot cross-depend).",
            why_it_matters="Cyclic or reverse dependencies between architectural layers break DAG order, increase blast radius, and undermine pipeline modularity.",
            how_to_fix="Move shared logic or models to an upstream intermediate or core layer, or reorganize models to respect layer hierarchy.",
            configuration_example="layers:\n  order: [staging, core, marts]\nchecks:\n  layer_integrity:\n    enabled: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}custom-exclusions-custom_exclusions",
            description="Enforces custom dependency boundaries between layers, domains, tags, or metadata selectors, and verifies allowed exceptions.",
            why_it_matters="Prevents unauthorized cross-domain dependencies (e.g. public models depending on PII models or marketing depending on unapproved finance tables).",
            how_to_fix="Remove the prohibited dependency, refactor to access an approved intermediate abstraction, or add a documented exception.",
            configuration_example="exclusions:\n  - source_layer: core\n    target_layer: derived\nchecks:\n  custom_exclusions:\n    enabled: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}dependency-graph-dependency_graph",
            description="Monitors the DAG shape for high coupling by checking inward coupling (fan_in) and outward blast radius (fan_out).",
            why_it_matters="Hub models with high fan-out carry immense blast radius when modified, while high fan-in models are brittle and prone to cascading upstream failures.",
            how_to_fix="Decompose monolithic models into smaller, focused transformation stages to balance fan-in and fan-out across the DAG.",
            configuration_example="checks:\n  dependency_graph:\n    enabled: true\n    fan_out_warn: 15\n    fan_out_fail: 25\n    fan_in_warn: 10",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}materialization-depth-materialization_depth",
            description="Calculates the nesting depth of models materialized as view. Views built on chains of views incur query planning and latency penalties.",
            why_it_matters="Deeply nested view chains degrade query performance, increase warehouse compute costs, and complicate query debugging.",
            how_to_fix="Materialize key intermediate or hub models as table or incremental to break the view chain.",
            configuration_example="checks:\n  materialization_depth:\n    enabled: true\n    max_depth_warn: 3\n    max_depth_fail: 5",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}environment-agnostic-references-environment_agnostic_references",
            description="Blocks hardcoded environment names or catalog prefixes (e.g. prod.raw.users or dev_db.schema.table).",
            why_it_matters="Hardcoding environment names prevents running models in development, testing, or isolated staging environments without manual code edits.",
            how_to_fix="Use relative model references (ref(...) or source(...)) so table locations resolve dynamically per environment.",
            configuration_example="rules:\n  environment_agnostic_references:\n    enabled: true\n    banned_environments: [prod, dev, staging, uat, qa]",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}metadata-metadata-partially-auto-fixable",
            description="Validates that every model has an assigned owner in its configuration or metadata.",
            why_it_matters="Unowned models lead to data pipeline abandonment, untracked bugs, and unclear escalation paths during data quality incidents.",
            how_to_fix="Assign an owner to the model in schema.yml, model config, or run 'tff lint --fix' to scaffold owner metadata.",
            configuration_example="rules:\n  metadata:\n    enabled: true\n    owner: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=True,
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
            docs_url=f"{docs_base}metadata-metadata-partially-auto-fixable",
            description="Validates that every model has a non-empty description documented in its metadata.",
            why_it_matters="Undocumented models create knowledge silos, slow down team onboarding, and make data discovery difficult.",
            how_to_fix="Add a clear description explaining the model's purpose and business context, or run 'tff lint --fix' to scaffold placeholder descriptions.",
            configuration_example="rules:\n  metadata:\n    enabled: true\n    description: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=True,
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
            docs_url=f"{docs_base}metadata-metadata-partially-auto-fixable",
            description="Validates that model primary keys / grains are explicitly documented in metadata.",
            why_it_matters="Without documented grains, downstream users cannot verify uniqueness, leading to unexpected duplicates in fan-out joins.",
            how_to_fix="Define the model grain column(s) in model metadata or configuration.",
            configuration_example="rules:\n  metadata:\n    enabled: true\n    grain: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}metadata-metadata-partially-auto-fixable",
            description="Validates that the model has not_null tests or audits defined on critical columns.",
            why_it_matters="Unexpected NULL values in key columns cause silent row drops in inner joins or incorrect metric calculations.",
            how_to_fix="Add a not_null test (dbt) or audit (SQLMesh) to the model primary keys.",
            configuration_example="rules:\n  metadata:\n    enabled: true\n    not_null: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}metadata-metadata-partially-auto-fixable",
            description="Validates that the model has unique tests or unique_values audits defined on its primary key columns.",
            why_it_matters="Duplicate records in dimension or mart tables cause fan-out errors when joined, inflating downstream aggregations.",
            how_to_fix="Add a unique test (dbt) or unique_values audit (SQLMesh) on the primary key column(s).",
            configuration_example="rules:\n  metadata:\n    enabled: true\n    unique_values: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}metadata-metadata-partially-auto-fixable",
            description="Validates that models have general data quality audits or tests configured.",
            why_it_matters="Untested models risk deploying broken data to production dashboards without detection.",
            how_to_fix="Configure appropriate audits or tests for the model.",
            configuration_example="rules:\n  metadata:\n    enabled: true",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=False,
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
            docs_url=f"{docs_base}sql-complexity-sql_complexity",
            description="Evaluates SQL maintainability metrics: CTE count, JOIN count, line count, decision points (CASE/IF), and nested subqueries in the final SELECT.",
            why_it_matters="Excessively complex SQL queries are difficult to test, review, and maintain, and frequently hide logical bugs and performance regressions.",
            how_to_fix="1. Refactor large queries by splitting them into smaller modular staging or intermediate models.\n2. Run 'tff lint --fix' to lift nested subqueries in final SELECT statements to CTEs.",
            configuration_example="rules:\n  sql_complexity:\n    enabled: true\n    thresholds:\n      decision_points: [15, 25]\n      cte_count: [8, 12]\n      join_count: [8, 12]\n      line_count: [250, 400]",
            providers=("dbt", "sqlmesh", "dataform"),
            is_fixable=True,
        )
    )

    reg.load_entry_points()
    return reg



registry: CheckRegistry = create_default_registry()
