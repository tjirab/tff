"""Dependency graph fan-in/fan-out metrics."""

from __future__ import annotations

from collections import defaultdict

from tff.core.model import ModelRepresentation
from tff.core.config import FitnessFunctionsConfig
from tff.core.report import LintFinding
from tff.core.utils.paths import model_path_relative


def collect_dependency_graph_findings(
    models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig
) -> list[LintFinding]:
    graph_config = config.checks.dependency_graph
    reverse: dict[str, set[str]] = defaultdict(set)
    for model_name, model in models.items():
        if model.is_symbolic:
            continue
        for dependency in model.depends_on:
            reverse[str(dependency)].add(str(model_name))

    findings: list[LintFinding] = []
    for model_name, model in models.items():
        if model.is_symbolic:
            continue

        from tff.core.utils.paths import get_layer_from_path
        layer = get_layer_from_path(model.path)
        if not graph_config.should_run(layer):
            continue

        fan_in = len(model.depends_on)
        fan_out = len(reverse.get(str(model_name), set()))

        if fan_out > graph_config.fan_out_fail:
            findings.append(
                LintFinding(
                    check="dependency_graph",
                    severity="error",
                    model=str(model_name),
                    path=model_path_relative(model),
                    message=(
                        f"fan_out={fan_out} (fail>{graph_config.fan_out_fail}) — "
                        "high blast-radius hub model"
                    ),
                )
            )
        elif fan_out > graph_config.fan_out_warn:
            findings.append(
                LintFinding(
                    check="dependency_graph",
                    severity="warning",
                    model=str(model_name),
                    path=model_path_relative(model),
                    message=(
                        f"fan_out={fan_out} (warn>{graph_config.fan_out_warn}) — "
                        "run impact analysis before changing"
                    ),
                )
            )

        if fan_in > graph_config.fan_in_warn:
            findings.append(
                LintFinding(
                    check="dependency_graph",
                    severity="warning",
                    model=str(model_name),
                    path=model_path_relative(model),
                    message=(
                        f"fan_in={fan_in} (warn>{graph_config.fan_in_warn}) — "
                        "consider decomposing upstream dependencies"
                    ),
                )
            )

    return findings
