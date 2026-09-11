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
    p = node.parent
    while isinstance(p, exp.Paren):
        p = p.parent
    if isinstance(p, exp.Neg):
        return f"-{val}"
    return val


def is_ignored_literal(node: exp.Literal) -> bool:
    # 1. Skip literals in LIMIT or OFFSET clauses
    p = node.parent
    while p:
        if isinstance(p, (exp.Limit, exp.Offset)):
            return True
        p = p.parent

    # 2. Skip data type definitions/parameters, e.g. decimal(15, 2), varchar(255)
    if node.find_ancestor(exp.DataTypeParam, exp.DataType):
        return True

    target = node
    while isinstance(target.parent, (exp.Paren, exp.Neg)):
        target = target.parent
    parent = target.parent
    if not parent:
        return False

    # 3. Round / Trunc precision/decimals argument, e.g. round(val, 2)
    if isinstance(parent, (exp.Round, exp.Trunc)) and target == parent.args.get("decimals"):
        return True

    # 4. SplitPart delimiter or part index, e.g. split_part(email, '@', 2)
    if isinstance(parent, exp.SplitPart) and target != parent.this:
        return True

    # 5. Positional slicing/substring functions
    if isinstance(parent, exp.Substring) and target != parent.this:
        return True
    if isinstance(parent, (exp.Left, exp.Right)) and target == parent.args.get("expression"):
        return True

    # 6. String concatenation operator (||)
    if isinstance(parent, exp.DPipe):
        return True

    # 7. Separator in concat_ws
    if isinstance(parent, exp.ConcatWs) and target == parent.expressions[0]:
        return True

    # 8. Divisor in arithmetic division, e.g. amount / 100.00 (cents to dollars divisor)
    if isinstance(parent, (exp.Div, exp.IntDiv)) and target == parent.args.get("expression"):
        return True

    return False


def collect_connascence_of_value_findings(
    models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig
) -> list[LintFinding]:
    rule_config = config.checks.connascence_of_value
    if not rule_config.enabled:
        return []

    # Map: lowercased_val -> list of occurrences (unique per model)
    value_occurrences: dict[str, list[dict]] = defaultdict(list)

    ignored_values_lower = {v.lower() for v in rule_config.ignored_values}
    ignored_punctuation_set = set(rule_config.ignored_punctuation)
    ignored_punctuation_chars = "".join(rule_config.ignored_punctuation)

    for model_name, model in models.items():
        if model.is_external or model.is_symbolic:
            continue

        layer = get_layer_from_path(model.path, layer_order=config.layers.order)
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

                if val_lower in ignored_values_lower:
                    continue

                if (
                    val in ignored_punctuation_set
                    or val_lower in {p.lower() for p in ignored_punctuation_set}
                    or (
                        ignored_punctuation_chars
                        and val.strip() in ignored_punctuation_set
                        and all(c in ignored_punctuation_chars for c in val)
                    )
                ):
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
