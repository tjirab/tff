"""Duplicate CTEs / Connascence of Algorithm check."""

from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from typing import TYPE_CHECKING

import sqlglot.expressions as exp

from tff.core.parallel import get_max_workers
from tff.core.report import LintFinding
from tff.core.utils.paths import get_layer_from_path, model_path_relative

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation

logger = logging.getLogger(__name__)


def is_complex_cte(cte_query: exp.Expression, min_nodes: int) -> bool:
    """Determine if a CTE query meets structural complexity heuristics."""
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


def extract_model_cte_fingerprints(
    task: tuple[str, str, str, exp.Expression | str | None, int],
) -> list[tuple[str, dict]]:
    """Extract complex CTE fingerprints for a single model (worker-safe)."""
    model_name, model_path, dialect, ast_or_sql, min_ast_nodes = task
    parsed: exp.Expression | None = None
    if isinstance(ast_or_sql, exp.Expression):
        parsed = ast_or_sql
    elif isinstance(ast_or_sql, str) and ast_or_sql.strip():
        from tff.core.ast_cache import parse_sql_with_cache
        from tff.core.parallel import _clean_sql_for_model

        cleaned = _clean_sql_for_model(ast_or_sql)
        parsed = parse_sql_with_cache(cleaned, dialect=dialect)

    if parsed is None:
        return []

    results: list[tuple[str, dict]] = []
    for cte in parsed.find_all(exp.CTE):
        cte_name = cte.alias
        cte_query = cte.this

        if not is_complex_cte(cte_query, min_ast_nodes):
            continue

        canonical_sql = cte_query.sql(dialect=dialect, pretty=False)
        h = hashlib.sha256(canonical_sql.encode("utf-8")).hexdigest()

        results.append((
            h,
            {
                "model": model_name,
                "path": model_path,
                "cte_name": cte_name,
                "canonical_sql": canonical_sql,
            },
        ))
    return results


def collect_duplicate_cte_findings(
    models: dict[str, ModelRepresentation],
    config: FitnessFunctionsConfig,
    max_workers: int | None = None,
) -> list[LintFinding]:
    """Identify duplicate complex CTE transformation logic across models in parallel."""
    rule_config = config.checks.duplicate_ctes
    if not rule_config.enabled:
        return []

    # Prepare fingerprint extraction tasks for eligible models
    tasks: list[tuple[str, str, str, exp.Expression | str | None, int]] = []
    for model in models.values():
        if model.is_external or model.is_symbolic:
            continue

        layer = get_layer_from_path(model.path, layer_order=config.layers.order)
        if not rule_config.should_run(layer):
            continue

        raw_or_parsed: exp.Expression | str | None = (
            model.expression if model.expression is not None else model.get_sql()
        )

        tasks.append((
            model.name,
            model.path,
            model.dialect,
            raw_or_parsed,
            rule_config.min_ast_nodes,
        ))

    fingerprints: dict[str, list[dict]] = defaultdict(list)

    if not tasks:
        return []

    workers = get_max_workers(config=config, override=max_workers)
    if workers <= 1 or len(tasks) <= 2:
        for task in tasks:
            for h, occ in extract_model_cte_fingerprints(task):
                fingerprints[h].append(occ)
    else:
        try:
            pool_size = min(workers, len(tasks))
            with ProcessPoolExecutor(max_workers=pool_size) as executor:
                chunksize = max(1, len(tasks) // (pool_size * 4))
                for model_results in executor.map(extract_model_cte_fingerprints, tasks, chunksize=chunksize):
                    for h, occ in model_results:
                        fingerprints[h].append(occ)
        except Exception as exc:
            logger.debug(
                "ProcessPoolExecutor encountered an issue in duplicate_ctes (%s), falling back to sequential",
                exc,
            )
            for task in tasks:
                for h, occ in extract_model_cte_fingerprints(task):
                    fingerprints[h].append(occ)

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
                others_str = (
                    ", and ".join(other_occs)
                    if len(other_occs) <= 2
                    else ", ".join(other_occs[:-1]) + f", and {other_occs[-1]}"
                )

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
