"""Unified lint runner orchestrating SQLMesh rules and architectural checks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from sqlmesh.core.context import Context
from sqlmesh.core.linter.definition import AnnotatedRuleViolation

from tff.core.adapter import normalize_project_roots
from tff.core.config import FitnessFunctionsConfig, load_fitness_config
from tff.core.model import ModelRepresentation
from tff.core.registry import CheckRegistry, normalize_check_name, registry
from tff.core.report import LintFinding, Severity, format_message, normalize_model_name
from tff.core.rules import ALL_RULES as CORE_RULES
from tff.core.utils.paths import model_path_relative
from tff.sqlmesh.loader import FitnessLoader, map_sqlmesh_model

logger = logging.getLogger(__name__)

CHECK_COLLECTORS = {
    c.finding_id: c.get_collector_fn()
    for c in registry.dag_checks()
    if c.get_collector_fn() is not None
}


class _SilentLinterConsole:
    def show_linter_violations(self, *args, **kwargs) -> None:
        return None


def collect_sqlmesh_findings(
    context: Context,
    config: FitnessFunctionsConfig | None = None,
    scoped_models: set[str] | None = None,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    silent_console = _SilentLinterConsole()

    if config is None and hasattr(context, "loader") and hasattr(context.loader, "_ff_config"):
        config = getattr(context.loader, "_ff_config", None)

    norm_scoped = (
        {normalize_model_name(m) for m in scoped_models}
        if scoped_models is not None
        else None
    )

    for model in context.models.values():
        if model.kind.is_symbolic:
            continue

        if norm_scoped is not None:
            m_name_str = str(model.name)
            if (
                m_name_str not in scoped_models  # type: ignore[operator]
                and normalize_model_name(m_name_str) not in norm_scoped
            ):
                continue

        linter = context._linters.get(model.project)
        if not linter or not linter.enabled:
            continue

        _, violations = linter.lint_model(model, context, console=silent_console)
        model_label = normalize_model_name(str(model.name))
        for violation in violations:
            if not isinstance(violation, AnnotatedRuleViolation):
                continue

            rule_name = violation.rule.name
            c_def = registry.get(rule_name)
            rule_severity = (
                c_def.get_severity(config)
                if c_def and config
                else violation.violation_type
            )

            message = format_message(violation.violation_msg)
            if message.startswith(f"{model_label}: "):
                message = message[len(model_label) + 2 :]

            is_sql_complexity = rule_name == "sqlcomplexity"
            if is_sql_complexity:
                from tff.core.rules.sql_complexity import split_complexity_message

                parsed_parts = split_complexity_message(
                    message, base_severity=rule_severity, model_name=model_label
                )
            else:
                base_sev: Severity = "warning" if rule_severity == "warning" else "error"
                parsed_parts = [(message, base_sev)]

            for part, part_severity in parsed_parts:

                v_line = None
                v_col = None
                v_end_line = None
                v_end_col = None
                v_range = getattr(violation, "violation_range", None)
                if v_range is not None:
                    if hasattr(v_range, "start") and v_range.start is not None:
                        v_line = getattr(v_range.start, "line", None)
                        v_col = getattr(v_range.start, "character", None)
                    if hasattr(v_range, "end") and v_range.end is not None:
                        v_end_line = getattr(v_range.end, "line", None)
                        v_end_col = getattr(v_range.end, "character", None)

                findings.append(
                    LintFinding(
                        check=violation.rule.name,
                        severity=part_severity,
                        model=str(model.name),
                        path=model_path_relative(model),
                        message=part,
                        line=v_line,
                        col=v_col,
                        end_line=v_end_line,
                        end_col=v_end_col,
                    )
                )

    return findings


def count_models_checked(context: Context) -> int:
    return sum(1 for model in context.models.values() if not model.kind.is_symbolic)


def _check_enabled(config: FitnessFunctionsConfig, check_name: str) -> bool:
    return registry.is_check_enabled(config, check_name, provider="sqlmesh")


def _run_collector_safely(
    name: str,
    collector,
    mapped_models: dict[str, ModelRepresentation],
    config: FitnessFunctionsConfig,
    scoped_models: set[str] | None = None,
    norm_scoped: set[str] | None = None,
) -> list[LintFinding]:
    try:
        dag_res = collector(mapped_models, config)
    except Exception as exc:
        logger.warning("Check '%s' failed to execute: %s", name, exc, exc_info=True)
        return [
            LintFinding(
                check="rule_execution_error",
                severity="warning",
                message=f"Check '{name}' failed with {type(exc).__name__}: {exc}",
            )
        ]

    if norm_scoped is not None:
        return [
            f
            for f in dag_res
            if f.model
            and (
                f.model in scoped_models  # type: ignore[operator]
                or normalize_model_name(str(f.model)) in norm_scoped
            )
        ]
    return dag_res


def collect_findings(
    context: Context | dict[str, ModelRepresentation],
    config: FitnessFunctionsConfig,
    checks: list[str] | None = None,
    scoped_models: set[str] | None = None,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    norm_scoped = (
        {normalize_model_name(m) for m in scoped_models}
        if scoped_models is not None
        else None
    )

    if isinstance(context, dict):
        mapped_models = context
        sqlmesh_ctx = None
    else:
        sqlmesh_ctx = context
        mapped_models = map_sqlmesh_context_models(context)

    selected = (
        checks
        if checks is not None
        else ["sqlmesh"] + [name for name in CHECK_COLLECTORS if _check_enabled(config, name)]
    )

    if "sqlmesh" in selected and sqlmesh_ctx is not None:
        findings.extend(
            collect_sqlmesh_findings(sqlmesh_ctx, config=config, scoped_models=scoped_models)
        )

    for name, collector in CHECK_COLLECTORS.items():
        if name in selected and collector is not None:
            findings.extend(
                _run_collector_safely(
                    name, collector, mapped_models, config, scoped_models, norm_scoped
                )
            )

    return findings


def get_executed_checks(
    config: FitnessFunctionsConfig,
    checks: list[str] | None = None,
) -> list[str]:
    selected = (
        checks
        if checks is not None
        else ["sqlmesh"] + [name for name in CHECK_COLLECTORS if _check_enabled(config, name)]
    )
    executed: list[str] = []
    for name in selected:
        if name == "sqlmesh":
            if config.rules.ban_select_star.enabled:
                executed.append("banselectstar")
            if config.rules.filename_equals_modelname.enabled:
                executed.append("filenameequalsmodelname")
            if config.rules.mart_naming.enabled:
                executed.append("martmodelnamingconvention")
            if config.rules.column_names.enabled and config.rules.column_names.replacements:
                executed.append("columnnames")
            if config.rules.column_types.enabled and config.rules.column_types.rules:
                executed.append("columntypes")
            if config.rules.classification_macros.enabled:
                executed.append("classificationmacros")
            if config.rules.sql_complexity.enabled:
                executed.append("sqlcomplexity")
            if config.rules.environment_agnostic_references.enabled:
                executed.append("environmentagnosticreferences")
            if (
                config.rules.no_positional_group_by.enabled
                and config.rules.no_positional_group_by_or_order_by.enabled
                and config.rules.no_positional_group_by_or_order_by.group_by
            ):
                executed.append("nopositionalgroupby")
            if (
                config.rules.no_positional_order_by.enabled
                and config.rules.no_positional_group_by_or_order_by.enabled
                and config.rules.no_positional_group_by_or_order_by.order_by
            ):
                executed.append("nopositionalorderby")
            if config.rules.metadata.enabled:
                if config.rules.metadata.owner:
                    executed.append("nomissingowner")
                if config.rules.metadata.description:
                    executed.append("nomissingdescription")
                if config.rules.metadata.grain:
                    executed.append("nomissinggrain")
                if config.rules.metadata.not_null:
                    executed.append("nomissingnotnull")
                if config.rules.metadata.unique_values:
                    executed.append("nomissinguniquevalues")
            for check_def in CheckRegistry.get_default().get_all_checks():
                if (
                    check_def.rule_cls is not None
                    and check_def.rule_cls not in CORE_RULES
                    and check_def.is_enabled(config, provider="sqlmesh")
                ):
                    executed.append(check_def.finding_id)
        else:
            executed.append(name)
    return executed


def map_sqlmesh_context_models(context: Context) -> dict[str, ModelRepresentation]:
    mapped = {}
    for model_name, model in context.models.items():
        mapped[str(model_name)] = map_sqlmesh_model(model)
    return mapped


def run_all_checks(
    project_root: Path | Sequence[Path] | None = None,
    context: Context | None = None,
    config: FitnessFunctionsConfig | None = None,
    checks: list[str] | None = None,
    models: dict[str, ModelRepresentation] | None = None,
    scoped_models: set[str] | None = None,
    chunk_size: int | None = None,
) -> tuple[list[LintFinding], int, list[str]]:
    roots = normalize_project_roots(project_root or Path.cwd())
    primary_root = roots[0]
    if config is None:
        config = load_fitness_config(primary_root)

    findings: list[LintFinding] = []
    norm_scoped = (
        {normalize_model_name(m) for m in scoped_models}
        if scoped_models is not None
        else None
    )

    if checks is None:
        selected = ["sqlmesh"] + [
            name for name in CHECK_COLLECTORS if _check_enabled(config, name)
        ]
        if context is None and models is None:
            context = Context(
                paths=[str(r) for r in roots],
                loader=FitnessLoader,
            )

        if context is not None:
            findings.extend(collect_sqlmesh_findings(context, config=config, scoped_models=scoped_models))

        mapped_models = (
            models if models is not None else map_sqlmesh_context_models(context)
        )

        for check_name, collector in CHECK_COLLECTORS.items():
            if _check_enabled(config, check_name) and collector is not None:
                findings.extend(
                    _run_collector_safely(
                        check_name,
                        collector,
                        mapped_models,
                        config,
                        scoped_models,
                        norm_scoped,
                    )
                )
    else:
        selected = checks
        # Validate checks or raise ValueError
        for chk in checks:
            norm = normalize_check_name(chk)
            if norm not in ("sqlmesh", "rules"):
                registry.get_or_raise(chk)

        model_rules_requested = any(
            normalize_check_name(c) == "rules"
            or (registry.get(c) is not None and registry.get(c).scope == "model")
            for c in checks
        )

        if context is None and (models is None or "sqlmesh" in selected):
            context = Context(
                paths=[str(r) for r in roots],
                loader=FitnessLoader,
            )

        mapped_models = (
            models
            if models is not None
            else (map_sqlmesh_context_models(context) if context is not None else {})
        )

        # Run SQLMesh linter / model rules
        if "sqlmesh" in selected:
            if context is not None:
                findings.extend(collect_sqlmesh_findings(context, config=config, scoped_models=scoped_models))
        elif model_rules_requested:
            if context is not None:
                all_sqlmesh_findings = collect_sqlmesh_findings(context, config=config, scoped_models=scoped_models)
                if any(normalize_check_name(c) == "rules" for c in checks):
                    findings.extend(all_sqlmesh_findings)
                else:
                    target_norms: set[str] = set()
                    for chk in checks:
                        c_def = registry.get(chk)
                        if c_def is not None and c_def.scope == "model":
                            target_norms.add(normalize_check_name(c_def.id))
                            target_norms.add(normalize_check_name(c_def.finding_id))
                            for alias in c_def.aliases:
                                target_norms.add(normalize_check_name(alias))
                    findings.extend(
                        [f for f in all_sqlmesh_findings if normalize_check_name(f.check) in target_norms]
                    )
            elif mapped_models:
                for chk in checks:
                    c_def = registry.get(chk)
                    if c_def is not None and c_def.scope == "model":
                        findings.extend(
                            c_def.run(
                                mapped_models,
                                config,
                                scoped_models=scoped_models,
                                chunk_size=chunk_size,
                            )
                        )

        # Run DAG checks
        for chk in checks:
            c_def = registry.get(chk)
            if c_def is not None and c_def.scope == "dag":
                collector = c_def.get_collector_fn()
                if collector is not None:
                    findings.extend(
                        _run_collector_safely(
                            c_def.finding_id,
                            collector,
                            mapped_models,
                            config,
                            scoped_models,
                            norm_scoped,
                        )
                    )

    if scoped_models is not None:
        checked_count = len(scoped_models)
    else:
        checked_count = (
            count_models_checked(context)
            if context is not None
            else sum(1 for m in mapped_models.values() if not m.is_symbolic)
        )

    return findings, checked_count, selected
