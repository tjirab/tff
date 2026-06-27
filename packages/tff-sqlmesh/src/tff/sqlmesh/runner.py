"""Unified lint runner orchestrating SQLMesh rules and architectural checks."""

from __future__ import annotations

import logging
from pathlib import Path

from sqlmesh.core.context import Context
from sqlmesh.core.linter.definition import AnnotatedRuleViolation

from tff.core.checks.custom_exclusions import collect_custom_exclusion_findings
from tff.core.checks.dependency_graph import collect_dependency_graph_findings
from tff.core.checks.layer_integrity import collect_layer_integrity_findings
from tff.core.checks.schema_contracts import collect_schema_contract_findings
from tff.core.config import FitnessFunctionsConfig, load_fitness_config
from tff.core.context import set_ff_config
from tff.core.report import LintFinding, format_message, normalize_model_name
from tff.core.utils.paths import model_path_relative
from tff.core.model import ModelRepresentation
from tff.sqlmesh.loader import FitnessLoader, map_sqlmesh_model

logger = logging.getLogger(__name__)

CHECK_COLLECTORS = {
    "layer_integrity": lambda models, cfg: collect_layer_integrity_findings(models, cfg),
    "custom_exclusions": lambda models, cfg: collect_custom_exclusion_findings(models, cfg),
    "schema_contracts": lambda _models, cfg: collect_schema_contract_findings(cfg),
    "dependency_graph": lambda models, cfg: collect_dependency_graph_findings(models, cfg),
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
    return sum(
        1 for model in context.models.values() if not model.kind.is_symbolic
    )


def _check_enabled(config: FitnessFunctionsConfig, check_name: str) -> bool:
    check = getattr(config.checks, check_name, None)
    return bool(getattr(check, "enabled", False))


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
) -> tuple[list[LintFinding], int, list[str]]:
    project_root = project_root or Path.cwd()
    if config is None:
        config = load_fitness_config(project_root)
    set_ff_config(config)

    context = context or Context(
        paths=[str(project_root)],
        loader=FitnessLoader,
    )

    if checks is None:
        selected = ["sqlmesh"] + [
            name
            for name in CHECK_COLLECTORS
            if _check_enabled(config, name)
        ]
    else:
        selected = checks

    findings: list[LintFinding] = []

    if "sqlmesh" in selected:
        findings.extend(collect_sqlmesh_findings(context))

    mapped_models = map_sqlmesh_context_models(context)

    for check_name, collector in CHECK_COLLECTORS.items():
        if check_name not in selected:
            continue
        if checks is None and not _check_enabled(config, check_name):
            continue
        findings.extend(collector(mapped_models, config))

    return findings, count_models_checked(context), selected
