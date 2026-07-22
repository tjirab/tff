"""Materialization depth (view nesting depth) check."""

from __future__ import annotations

from tff.core.model import ModelRepresentation
from tff.core.config import FitnessFunctionsConfig
from tff.core.report import LintFinding
from tff.core.utils.paths import model_path_relative, get_layer_from_path


def collect_materialization_depth_findings(
    models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig
) -> list[LintFinding]:
    depth_config = config.checks.materialization_depth
    if not depth_config.enabled:
        return []

    memo: dict[str, int] = {}
    visiting: set[str] = set()

    def get_view_depth(m_key: str) -> int:
        if m_key in memo:
            return memo[m_key]
        if m_key in visiting:
            return 0  # Safe cycle protection

        model = models.get(m_key)
        if not model or model.is_symbolic or model.materialized != "view":
            return 0

        visiting.add(m_key)
        max_parent_depth = 0
        for dep in model.depends_on:
            max_parent_depth = max(max_parent_depth, get_view_depth(str(dep)))
        visiting.remove(m_key)

        memo[m_key] = max_parent_depth + 1
        return memo[m_key]

    findings: list[LintFinding] = []
    for model_name, model in models.items():
        if model.is_symbolic or model.is_external:
            continue

        layer = get_layer_from_path(model.path)
        if not depth_config.should_run(layer):
            continue

        if model.materialized != "view":
            continue

        depth = get_view_depth(str(model_name))
        if depth > depth_config.max_depth_fail:
            findings.append(
                LintFinding(
                    check="materialization_depth",
                    severity="error",
                    model=str(model_name),
                    path=model_path_relative(model),
                    message=(
                        f"View nesting depth is {depth} (fail>{depth_config.max_depth_fail}). "
                        "Consider materializing as TABLE or INCREMENTAL."
                    ),
                )
            )
        elif depth > depth_config.max_depth_warn:
            findings.append(
                LintFinding(
                    check="materialization_depth",
                    severity="warning",
                    model=str(model_name),
                    path=model_path_relative(model),
                    message=(
                        f"View nesting depth is {depth} (warn>{depth_config.max_depth_warn}). "
                        "Consider materializing as TABLE or INCREMENTAL."
                    ),
                )
            )

    return findings
