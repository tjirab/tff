"""Layer integrity check — unidirectional flow and mart domain isolation."""

from __future__ import annotations

from tff.core.model import ModelRepresentation
from tff.core.config import FitnessFunctionsConfig
from tff.core.report import LintFinding, normalize_model_name
from tff.core.utils.paths import (
    get_layer_from_path,
    get_marts_domain_from_path,
    model_path_relative,
)


def _layer_index(
    layer: str | None, dependency_model_kind: str, layer_order: list[str]
) -> int | None:
    layer_index = {name: idx for idx, name in enumerate(layer_order)}
    if layer:
        return layer_index.get(layer)
    if dependency_model_kind == "EXTERNAL":
        return -1
    return None


def collect_layer_integrity_findings(
    models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    layer_order = config.layers.order
    marts_layer = config.rules.mart_naming.layer_name

    for model_name, model in models.items():
        if model.is_external or model.is_symbolic:
            continue

        model_layer = get_layer_from_path(model.path, layer_order)
        model_layer_index = _layer_index(model_layer, "EXTERNAL" if model.is_external else "STANDARD", layer_order)
        model_marts_domain = (
            get_marts_domain_from_path(model.path, marts_layer)
            if model_layer == marts_layer
            else None
        )

        for dependency in model.depends_on:
            dependency_model = models.get(dependency)
            if not dependency_model:
                continue

            dependency_layer = get_layer_from_path(dependency_model.path, layer_order)
            dependency_layer_index = _layer_index(
                dependency_layer,
                "EXTERNAL" if dependency_model.is_external else "STANDARD",
                layer_order,
            )

            if (
                model_layer_index is not None
                and dependency_layer_index is not None
                and dependency_layer_index > model_layer_index
            ):
                findings.append(
                    LintFinding(
                        check="layer_integrity",
                        severity="error",
                        model=str(model.name),
                        path=model_path_relative(model),
                        message=(
                            f"depends on {normalize_model_name(str(dependency))} "
                            "in a downstream layer"
                        ),
                    )
                )

            if model_layer == marts_layer and dependency_layer == marts_layer:
                dependency_marts_domain = get_marts_domain_from_path(
                    dependency_model.path, marts_layer
                )
                if (
                    model_marts_domain
                    and dependency_marts_domain
                    and model_marts_domain != dependency_marts_domain
                ):
                    findings.append(
                        LintFinding(
                            check="layer_integrity",
                            severity="error",
                            model=str(model.name),
                            path=model_path_relative(model),
                            message=(
                                f"{marts_layer}/{model_marts_domain} depends on "
                                f"{normalize_model_name(str(dependency))} "
                                f"({marts_layer}/{dependency_marts_domain})"
                            ),
                        )
                    )

    return findings
