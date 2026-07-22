"""Duplicate CTEs / Connascence of Algorithm check."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from pathlib import Path

import sqlglot
import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.config import FitnessFunctionsConfig
from tff.core.report import LintFinding
from tff.core.utils.paths import model_path_relative, get_layer_from_path


def is_complex_cte(cte_query: exp.Expression, min_nodes: int) -> bool:
    # Heuristic 1: Check node count
    node_count = sum(1 for _ in cte_query.walk())
    if node_count < min_nodes:
        return False

    # Heuristic 2: Check structural complexity (Join, Where, Group/Having, Window, Case/If)
    has_complex_structure = any(
        cte_query.find(cls) is not None
        for cls in (exp.Join, exp.Where, exp.Group, exp.Having, exp.Window, exp.Case, exp.If)
    )
    return has_complex_structure


def collect_duplicate_cte_findings(
    models: dict[str, ModelRepresentation], config: FitnessFunctionsConfig
) -> list[LintFinding]:
    rule_config = config.checks.duplicate_ctes
    if not rule_config.enabled:
        return []

    # Map fingerprint (SHA-256) -> list of dict(model, path, cte_name, canonical_sql)
    fingerprints: dict[str, list[dict]] = defaultdict(list)

    for model_name, model in models.items():
        if model.is_external or model.is_symbolic:
            continue

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            continue

        sql = model.query
        if sql is None:
            path = Path(model.path)
            if path.suffix != ".sql" or not path.exists():
                continue
            try:
                sql = path.read_text(encoding="utf-8")
            except Exception:
                continue

        try:
            # Strip SQLMesh MODEL block if present
            sql = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
            parsed = sqlglot.parse_one(sql, read=model.dialect)
        except Exception:
            continue

        for cte in parsed.find_all(exp.CTE):
            cte_name = cte.alias
            cte_query = cte.this

            if not is_complex_cte(cte_query, rule_config.min_ast_nodes):
                continue

            canonical_sql = cte_query.sql(dialect=model.dialect, pretty=False)
            h = hashlib.sha256(canonical_sql.encode("utf-8")).hexdigest()

            fingerprints[h].append({
                "model": model.name,
                "path": model.path,
                "cte_name": cte_name,
                "canonical_sql": canonical_sql,
            })

    findings: list[LintFinding] = []
    # Identify fingerprints that have occurrences across multiple models or multiple times
    for occurrences in fingerprints.values():
        if len(occurrences) > 1:
            for i, occ in enumerate(occurrences):
                other_occs = [
                    f"model '{o['model']}' (CTE '{o['cte_name']}')"
                    for j, o in enumerate(occurrences)
                    if j != i
                ]
                others_str = ", and ".join(other_occs) if len(other_occs) <= 2 else ", ".join(other_occs[:-1]) + f", and {other_occs[-1]}"
                
                # Format severity type: warning or error
                severity_type = "error" if rule_config.severity == "error" else "warning"
                
                message = (
                    f"CTE '{occ['cte_name']}' has duplicate transformation logic with {others_str}. "
                    "This indicates Connascence of Algorithm (CoA) and should be refactored into a shared upstream model or macro."
                )

                findings.append(
                    LintFinding(
                        check="duplicate_ctes",
                        severity=severity_type,
                        model=occ["model"],
                        path=model_path_relative(occ),
                        message=message,
                    )
                )

    return findings
