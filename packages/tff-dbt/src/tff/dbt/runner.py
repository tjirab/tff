"""Orchestrator runner executing tff-core rules and checks against dbt manifest models."""

from __future__ import annotations

import logging
from pathlib import Path

from tff.core.checks.custom_exclusions import collect_custom_exclusion_findings
from tff.core.checks.dependency_graph import collect_dependency_graph_findings
from tff.core.checks.layer_integrity import collect_layer_integrity_findings
from tff.core.checks.schema_contracts import collect_schema_contract_findings
from tff.core.config import FitnessFunctionsConfig, load_fitness_config
from tff.core.context import set_ff_config
from tff.core.report import LintFinding
from tff.core.rules import ALL_RULES
from tff.core.utils.paths import model_path_relative
from tff.core.model import ModelRepresentation
from tff.dbt.manifest import load_dbt_models

logger = logging.getLogger(__name__)

CHECK_COLLECTORS = {
    "layer_integrity": lambda models, cfg: collect_layer_integrity_findings(models, cfg),
    "custom_exclusions": lambda models, cfg: collect_custom_exclusion_findings(models, cfg),
    "schema_contracts": lambda _models, cfg: collect_schema_contract_findings(cfg),
    "dependency_graph": lambda models, cfg: collect_dependency_graph_findings(models, cfg),
}


def collect_dbt_rules_findings(models: dict[str, ModelRepresentation]) -> list[LintFinding]:
    findings = []
    rules = [rule_cls() for rule_cls in ALL_RULES]

    for model in models.values():
        if model.is_external or model.is_symbolic:
            continue

        for rule in rules:
            violation = rule.check_model(model)
            if violation:
                msgs = violation.violation_msg
                if isinstance(msgs, str):
                    msgs = [msgs]
                for msg in msgs:
                    # Strip model name prefix from message if the rule prepended it
                    model_label = f"{model.name}: "
                    clean_msg = msg.removeprefix(model_label)

                    findings.append(
                        LintFinding(
                            check=rule.name,
                            severity="error",
                            model=model.name,
                            path=model_path_relative(model),
                            message=clean_msg,
                        )
                    )
    return findings


def _check_enabled(config: FitnessFunctionsConfig, check_name: str) -> bool:
    check = getattr(config.checks, check_name, None)
    return bool(getattr(check, "enabled", False))


def run_all_checks(
    project_root: Path | None = None,
    config: FitnessFunctionsConfig | None = None,
    checks: list[str] | None = None,
    dialect: str = "bigquery",
) -> tuple[list[LintFinding], int, list[str]]:
    project_root = project_root or Path.cwd()
    if config is None:
        config = load_fitness_config(project_root)
    set_ff_config(config)

    # Parse and load manifest.json
    models = load_dbt_models(project_root, dialect=dialect)

    if checks is None:
        selected = ["rules"] + [
            name
            for name in CHECK_COLLECTORS
            if _check_enabled(config, name)
        ]
    else:
        selected = checks

    findings: list[LintFinding] = []

    if "rules" in selected:
        findings.extend(collect_dbt_rules_findings(models))

    for check_name, collector in CHECK_COLLECTORS.items():
        if check_name not in selected:
            continue
        findings.extend(collector(models, config))

    models_checked = sum(
        1 for m in models.values() if not m.is_external and not m.is_symbolic
    )

    return findings, models_checked, selected
