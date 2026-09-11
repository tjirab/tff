"""Unified lint runner orchestrating SQLMesh rules and architectural checks."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmesh.core.context import Context
from sqlmesh.core.linter.definition import AnnotatedRuleViolation

from tff.core.config import FitnessFunctionsConfig, load_fitness_config
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.registry import normalize_check_name, registry
from tff.core.report import LintFinding, format_message, normalize_model_name
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


def collect_sqlmesh_findings(context: Context) -> list[LintFinding]:
    findings: list[LintFinding] = []
    silent_console = _SilentLinterConsole()

    for model in context.models.values():
        if model.kind.is_symbolic:
            continue

        linter = context._linters.get(model.project)
        if not linter or not linter.enabled:
            continue

        _, violations = linter.lint_model(model, context, console=silent_console)
        model_label = normalize_model_name(str(model.name))
        for violation in violations:
            if not isinstance(violation, AnnotatedRuleViolation):
                continue

            message = format_message(violation.violation_msg)
            if message.startswith(f"{model_label}: "):
                message = message[len(model_label) + 2 :]

            messages = (
                [part.strip() for part in message.split(";") if part.strip()]
                if violation.rule.name == "sqlcomplexity"
                else [message]
            )

            for part in messages:
                findings.append(
                    LintFinding(
                        check=violation.rule.name,
                        severity=violation.violation_type,
                        model=str(model.name),
                        path=model_path_relative(model),
                        message=part,
                    )
                )

    return findings


def count_models_checked(context: Context) -> int:
    return sum(1 for model in context.models.values() if not model.kind.is_symbolic)


def _check_enabled(config: FitnessFunctionsConfig, check_name: str) -> bool:
    return registry.is_check_enabled(config, check_name, provider="sqlmesh")


def map_sqlmesh_context_models(context: Context) -> dict[str, ModelRepresentation]:
    mapped = {}
    for model_name, model in context.models.items():
        mapped[str(model_name)] = map_sqlmesh_model(model)
    return mapped


def run_all_checks(
    project_root: Path | None = None,
    context: Context | None = None,
    config: FitnessFunctionsConfig | None = None,
    checks: list[str] | None = None,
    models: dict[str, ModelRepresentation] | None = None,
) -> tuple[list[LintFinding], int, list[str]]:
    project_root = project_root or Path.cwd()
    if config is None:
        config = load_fitness_config(project_root)
    set_ff_config(config)

    findings: list[LintFinding] = []

    if checks is None:
        selected = ["sqlmesh"] + [
            name for name in CHECK_COLLECTORS if _check_enabled(config, name)
        ]
        if context is None and models is None:
            context = Context(
                paths=[str(project_root)],
                loader=FitnessLoader,
            )

        if context is not None:
            findings.extend(collect_sqlmesh_findings(context))

        mapped_models = (
            models if models is not None else map_sqlmesh_context_models(context)
        )

        for check_name, collector in CHECK_COLLECTORS.items():
            if _check_enabled(config, check_name) and collector is not None:
                findings.extend(collector(mapped_models, config))
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
                paths=[str(project_root)],
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
                findings.extend(collect_sqlmesh_findings(context))
        elif model_rules_requested:
            if context is not None:
                all_sqlmesh_findings = collect_sqlmesh_findings(context)
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
                        findings.extend(c_def.run(mapped_models, config))

        # Run DAG checks
        for chk in checks:
            c_def = registry.get(chk)
            if c_def is not None and c_def.scope == "dag":
                collector = c_def.get_collector_fn()
                if collector is not None:
                    findings.extend(collector(mapped_models, config))

    checked_count = (
        count_models_checked(context)
        if context is not None
        else sum(1 for m in mapped_models.values() if not m.is_symbolic)
    )

    return findings, checked_count, selected
