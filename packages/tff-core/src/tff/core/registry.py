"""Centralized, declarative CheckRegistry for fitness checks and rules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Callable, Literal

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding, Severity
    from tff.core.rules.base import Rule

Scope = Literal["model", "dag"]


@lru_cache(maxsize=512)
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
            cached = getattr(self, "_cached_rule_cls", None)
            if cached is not None:
                return cached
            import importlib

            mod = importlib.import_module(self.rule_module)
            cls = getattr(mod, self.rule_class_name)
            object.__setattr__(self, "_cached_rule_cls", cls)
            return cls
        return None

    def get_collector_fn(self) -> Callable | None:
        if self.collector_fn is not None:
            return self.collector_fn
        if self.collector_module and self.collector_func_name:
            cached = getattr(self, "_cached_collector_fn", None)
            if cached is not None:
                return cached
            import importlib

            mod = importlib.import_module(self.collector_module)
            fn = getattr(mod, self.collector_func_name)
            object.__setattr__(self, "_cached_collector_fn", fn)
            return fn
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
        scoped_models: set[str] | None = None,
    ) -> list[LintFinding]:
        if self.scope == "model":
            rule_cls = self.get_rule_cls()
            if rule_cls is not None:
                severity = self.get_severity(config)
                target_models = (
                    {k: v for k, v in models.items() if k in scoped_models}
                    if scoped_models is not None
                    else models
                )
                if not target_models:
                    return []
                return run_model_rule(
                    rule_cls,
                    target_models,
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
                    findings = collector(models, config, max_workers=max_workers)
                else:
                    findings = collector(models, config)

                if scoped_models is not None:
                    from tff.core.report import normalize_model_name

                    norm_scoped = {normalize_model_name(m) for m in scoped_models}
                    return [
                        f
                        for f in findings
                        if f.model and (f.model in scoped_models or normalize_model_name(f.model) in norm_scoped)
                    ]
                return findings
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

    @classmethod
    def get_default(cls) -> CheckRegistry:
        return registry

    def get_all_checks(self) -> list[CheckDefinition]:
        return list(self._checks.values())

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
            elif norm in ("nopositionalgroupbyororderby", "no_positional_group_by_or_order_by"):
                for pos_id in ("no_positional_group_by", "no_positional_order_by"):
                    c = self.get(pos_id)
                    if c and c.id not in seen:
                        seen.add(c.id)
                        resolved.append(c)
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
        scoped_models: set[str] | None = None,
        chunk_size: int | None = None,
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
                    res = check_def.run(
                        models,
                        config,
                        max_workers=workers,
                        scoped_models=scoped_models,
                        chunk_size=chunk_size,
                    )
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
                        res = c.run(
                            models,
                            config,
                            max_workers=1,
                            scoped_models=scoped_models,
                            chunk_size=chunk_size,
                        )
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
    """Create and populate the default global CheckRegistry with all built-in checks."""
    from tff.core.catalog import register_builtin_checks

    reg = CheckRegistry()
    register_builtin_checks(reg)
    reg.load_entry_points()
    return reg


registry: CheckRegistry = create_default_registry()
