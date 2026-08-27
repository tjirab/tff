"""Connascence of Value (CoV) check."""

from __future__ import annotations

from collections import defaultdict

import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.config import FitnessFunctionsConfig
from tff.core.report import LintFinding
from tff.core.utils.paths import model_path_relative, get_layer_from_path


def get_literal_value(node: exp.Literal) -> str:
    val = node.this
    if isinstance(node.parent, exp.Neg):
        return f"-{val}"
    return val


def is_ignored_literal(node: exp.Literal) -> bool:
    p = node.parent
    while p:
        if isinstance(p, (exp.Limit, exp.Offset)):
            return True
        p = p.parent
    return False


def collect_connascence_of_value_findings(
    models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig
) -> list[LintFinding]:
    rule_config = config.checks.connascence_of_value
    if not rule_config.enabled:
        return []

    # Map: lowercased_val -> list of occurrences (unique per model)
    value_occurrences: dict[str, list[dict]] = defaultdict(list)

    for model_name, model in models.items():
        if model.is_external or model.is_symbolic:
            continue

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            continue

        parsed = model.ast
        if parsed is None:
            continue

        seen_in_model: set[str] = set()
        for node in parsed.walk():
            if isinstance(node, exp.Literal):
                if is_ignored_literal(node):
                    continue

                val = get_literal_value(node)
                val_lower = val.lower()

                if val_lower in [v.lower() for v in rule_config.ignored_values]:
                    continue

                if val_lower in seen_in_model:
                    continue
                seen_in_model.add(val_lower)

                value_occurrences[val_lower].append({
                    "model": model.name,
                    "path": model.path,
                    "val": val,
                })

    findings: list[LintFinding] = []
    # Identify values that occur across at least min_occurrences unique models
    for val_lower, occurrences in value_occurrences.items():
        if len(occurrences) >= rule_config.min_occurrences:
            for i, occ in enumerate(occurrences):
                other_occs = [
                    f"model '{o['model']}'"
                    for j, o in enumerate(occurrences)
                    if j != i
                ]
                if len(other_occs) <= 2:
                    others_str = " and ".join(other_occs)
                else:
                    others_str = ", ".join(other_occs[:-1]) + f", and {other_occs[-1]}"

                severity_type = "error" if rule_config.severity == "error" else "warning"
                
                message = (
                    f"Literal '{occ['val']}' is duplicated in {others_str}. "
                    "This indicates Connascence of Value (CoV) and should be promoted to a seed or project-level variable."
                )

                findings.append(
                    LintFinding(
                        check="connascence_of_value",
                        severity=severity_type,
                        model=occ["model"],
                        path=model_path_relative(occ),
                        message=message,
                    )
                )

    return findings
