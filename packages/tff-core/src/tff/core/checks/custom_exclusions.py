"""Custom dependency exclusion rules for layer/domain boundaries."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tff.core.model import ModelRepresentation
from tff.core.config import FitnessFunctionsConfig, resolve_project_path
from tff.core.report import LintFinding
from tff.core.utils.paths import model_path_relative, resolve_layer_and_domain

logger = logging.getLogger(__name__)


class CustomExclusionsChecker:
    """Enforce custom exclusions for model dependencies between layers."""

    def __init__(
        self,
        models: dict[str, ModelRepresentation],
        exclusions_path: Path,
        config: FitnessFunctionsConfig | None = None,
    ):
        self.models = models
        self.exclusions_path = exclusions_path
        self.config = config
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

        if self.config and self.config.checks.custom_exclusions:
            config_exclusions = self.config.checks.custom_exclusions
            if hasattr(config_exclusions, "allowed_exceptions") and config_exclusions.allowed_exceptions:
                for exception in config_exclusions.allowed_exceptions:
                    if (
                        self._normalize_model_name(exception.model) == normalized_model
                        and self._normalize_model_name(exception.dependency) == normalized_dependency
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
        source_model: ModelRepresentation | None = None,
        target_model: ModelRepresentation | None = None,
    ) -> bool:
        if model_name and dependency_name:
            if self._is_allowed_exception(model_name, dependency_name):
                return False

        if not source_model and dependency_name:
            source_model = self.models.get(dependency_name)
        if not target_model and model_name:
            target_model = self.models.get(model_name)

        # 1. JSON exclusions
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

        # 2. Config exclusions (fitness_functions.yaml)
        if self.config and self.config.checks.custom_exclusions:
            config_exclusions = self.config.checks.custom_exclusions
            if hasattr(config_exclusions, "exclusions") and config_exclusions.exclusions:
                for exclusion in config_exclusions.exclusions:
                    source_match = True
                    if exclusion.source_layer is not None and exclusion.source_layer != source_layer:
                        source_match = False
                    if exclusion.source_domain is not None and exclusion.source_domain != source_domain:
                        source_match = False
                    
                    if source_model:
                        if exclusion.source_tag is not None and exclusion.source_tag not in (source_model.tags or []):
                            source_match = False
                        if exclusion.source_tags:
                            for tag in exclusion.source_tags:
                                if tag not in (source_model.tags or []):
                                    source_match = False
                                    break
                        if exclusion.source_meta:
                            for k, v in exclusion.source_meta.items():
                                if not source_model.meta or source_model.meta.get(k) != v:
                                    source_match = False
                                    break
                    else:
                        if exclusion.source_tag or exclusion.source_tags or exclusion.source_meta:
                            source_match = False

                    target_match = True
                    if exclusion.target_layer is not None and exclusion.target_layer != target_layer:
                        target_match = False
                    if exclusion.target_domain is not None and exclusion.target_domain != target_domain:
                        target_match = False
                    
                    if target_model:
                        if exclusion.target_tag is not None and exclusion.target_tag not in (target_model.tags or []):
                            target_match = False
                        if exclusion.target_tags:
                            for tag in exclusion.target_tags:
                                if tag not in (target_model.tags or []):
                                    target_match = False
                                    break
                        if exclusion.target_meta:
                            for k, v in exclusion.target_meta.items():
                                if not target_model.meta or target_model.meta.get(k) != v:
                                    target_match = False
                                    break
                    else:
                        if exclusion.target_tag or exclusion.target_tags or exclusion.target_meta:
                            target_match = False

                    if source_match and target_match:
                        return True

        return False

    def check_model(self, model: ModelRepresentation) -> list[str]:
        if model.is_symbolic:
            return []

        violations = []
        from tff.core.context import get_ff_config

        if self.config:
            layer_order = self.config.layers.order
            marts_layer = self.config.rules.mart_naming.layer_name
        else:
            layer_order = get_ff_config().layers.order
            marts_layer = get_ff_config().rules.mart_naming.layer_name

        model_layer, model_domain = resolve_layer_and_domain(model, layer_order, marts_layer)
        if not model_layer:
            return []

        for dependency_name in model.depends_on:
            try:
                dependency_model = self.models.get(dependency_name)
                if not dependency_model:
                    continue

                dep_layer, dep_domain = resolve_layer_and_domain(dependency_model, layer_order, marts_layer)
                if not dep_layer:
                    continue

                if self._is_excluded_dependency(
                    source_layer=dep_layer,
                    source_domain=dep_domain or "",
                    target_layer=model_layer,
                    target_domain=model_domain or "",
                    model_name=str(model.name),
                    dependency_name=str(dependency_name),
                    source_model=dependency_model,
                    target_model=model,
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
    checker = CustomExclusionsChecker(models, exclusions_path, config=config)
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
