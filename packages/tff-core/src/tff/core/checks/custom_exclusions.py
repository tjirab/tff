"""Custom dependency exclusion rules for layer/domain boundaries."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tff.core.model import ModelRepresentation
from tff.core.config import FitnessFunctionsConfig, resolve_project_path
from tff.core.report import LintFinding
from tff.core.utils.paths import get_layer_and_domain, model_path_relative

logger = logging.getLogger(__name__)


class CustomExclusionsChecker:
    """Enforce custom exclusions for model dependencies between layers."""

    def __init__(self, models: dict[str, ModelRepresentation], exclusions_path: Path):
        self.models = models
        self.exclusions_path = exclusions_path
        self.exclusions = self._load_exclusions()

    def _load_exclusions(self) -> dict:
        if not self.exclusions_path.exists():
            logger.warning(
                "Config file %s not found. No exclusions will be enforced.",
                self.exclusions_path,
            )
            return {}

        try:
            with open(self.exclusions_path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "Could not load exclusions config from %s: %s",
                self.exclusions_path,
                e,
            )
            return {}

    def _normalize_model_name(self, name: str) -> str:
        parts = name.replace('"', "").split(".")
        if len(parts) >= 2:
            return f"{parts[-2]}.{parts[-1]}"
        return name

    def _is_allowed_exception(self, model_name: str, dependency_name: str) -> bool:
        normalized_model = self._normalize_model_name(model_name)
        normalized_dependency = self._normalize_model_name(dependency_name)

        for exception in self.exclusions.get("allowed_exceptions", []):
            if (
                exception.get("model") == normalized_model
                and exception.get("dependency") == normalized_dependency
            ):
                return True
        return False

    def _is_excluded_dependency(
        self,
        source_layer: str,
        source_domain: str,
        target_layer: str,
        target_domain: str,
        model_name: str | None = None,
        dependency_name: str | None = None,
    ) -> bool:
        if model_name and dependency_name:
            if self._is_allowed_exception(model_name, dependency_name):
                return False

        for exclusion in self.exclusions.get("exclusions", []):
            source_match = True
            if (
                "source_layer" in exclusion
                and exclusion["source_layer"] != source_layer
            ):
                source_match = False
            if (
                "source_domain" in exclusion
                and exclusion["source_domain"] != source_domain
            ):
                source_match = False

            target_match = True
            if (
                "target_layer" in exclusion
                and exclusion["target_layer"] != target_layer
            ):
                target_match = False
            if (
                "target_domain" in exclusion
                and exclusion["target_domain"] != target_domain
            ):
                target_match = False

            if source_match and target_match:
                return True

        return False

    def check_model(self, model: ModelRepresentation) -> list[str]:
        if model.is_symbolic:
            return []

        violations = []
        model_layer, model_domain = get_layer_and_domain(model.path)
        if not model_layer:
            return []

        for dependency_name in model.depends_on:
            try:
                dependency_model = self.models.get(dependency_name)
                if not dependency_model:
                    continue

                dep_layer, dep_domain = get_layer_and_domain(dependency_model.path)
                if not dep_layer:
                    continue

                if self._is_excluded_dependency(
                    source_layer=dep_layer,
                    source_domain=dep_domain or "",
                    target_layer=model_layer,
                    target_domain=model_domain or "",
                    model_name=str(model.name),
                    dependency_name=str(dependency_name),
                ):
                    violations.append(
                        f"Model '{model.name}' in layer '{model_layer}"
                        f"{f'/{model_domain}' if model_domain else ''}' "
                        f"depends on '{dependency_name}' in layer '{dep_layer}"
                        f"{f'/{dep_domain}' if dep_domain else ''}', "
                        f"which is not allowed by custom exclusions"
                    )
            except Exception as e:
                logger.error(
                    "Unexpected error checking dependency %s for model %s: %s",
                    dependency_name,
                    model.name,
                    e,
                    exc_info=True,
                )
                continue

        return violations


def collect_custom_exclusion_findings(
    models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig
) -> list[LintFinding]:
    exclusions_path = resolve_project_path(config, config.exclusions_path)
    checker = CustomExclusionsChecker(models, exclusions_path)
    findings: list[LintFinding] = []

    for model_name, model in models.items():
        if model.is_symbolic:
            continue

        for message in checker.check_model(model):
            findings.append(
                LintFinding(
                    check="custom_exclusions",
                    severity="error",
                    model=str(model.name),
                    path=model_path_relative(model),
                    message=message.removeprefix(f"Model '{model.name}' ").strip(),
                )
            )

    return findings
