"""Orchestrator runner executing tff-core rules and checks against dbt manifest models."""

from __future__ import annotations

import logging
from pathlib import Path

from tff.core.config import FitnessFunctionsConfig, load_fitness_config
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.registry import registry
from tff.core.report import LintFinding
from tff.dbt.manifest import load_dbt_models

logger = logging.getLogger(__name__)

CHECK_COLLECTORS = {
    c.finding_id: c.get_collector_fn()
    for c in registry.dag_checks()
    if c.get_collector_fn() is not None
}


def collect_dbt_rules_findings(
    models: dict[str, ModelRepresentation],
    config: FitnessFunctionsConfig | None = None,
) -> list[LintFinding]:
    """Collect findings for all registered model-level rules."""
    findings: list[LintFinding] = []
    for rule_def in registry.model_rules():
        findings.extend(rule_def.run(models, config=config))
    return findings


def _check_enabled(config: FitnessFunctionsConfig, check_name: str) -> bool:
    return registry.is_check_enabled(config, check_name, provider="dbt")


def run_all_checks(
    project_root: Path | None = None,
    config: FitnessFunctionsConfig | None = None,
    checks: list[str] | None = None,
    dialect: str | None = None,
    models: dict[str, ModelRepresentation] | None = None,
) -> tuple[list[LintFinding], int, list[str]]:
    project_root = project_root or Path.cwd()
    if config is None:
        config = load_fitness_config(project_root)
    set_ff_config(config)

    # Parse and load manifest.json if models not already provided
    if models is None:
        models = load_dbt_models(project_root, dialect=dialect)

    findings, selected = registry.run_checks(
        models=models,
        config=config,
        checks=checks,
        provider="dbt",
    )

    models_checked = sum(
        1 for m in models.values() if not m.is_external and not m.is_symbolic
    )

    return findings, models_checked, selected
