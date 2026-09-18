"""Worker pool utilities for parallel AST parsing, rule execution, and CTE fingerprinting."""

from __future__ import annotations

import logging
import os
import re
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tff.core.ast_cache import (
    compute_ast_cache_key,
    get_ast_cache_dir,
    get_cached_ast,
    is_cache_enabled,
    parse_sql_with_cache,
)
from tff.core.model import read_model_sql
from tff.core.utils.jinja import clean_dataform_for_parsing, clean_jinja_for_parsing

if TYPE_CHECKING:
    import sqlglot.expressions as exp
    from tff.core.config import FitnessFunctionsConfig
    from tff.core.model import ModelRepresentation
    from tff.core.report import LintFinding, Severity
    from tff.core.rules.base import Rule, RuleViolation

logger = logging.getLogger(__name__)


def get_max_workers(
    config: FitnessFunctionsConfig | None = None,
    override: int | None = None,
) -> int:
    """Determine the maximum number of worker processes or threads to use."""
    if override is not None:
        return max(1, int(override))

    env_tff = os.environ.get("TFF_WORKERS") or os.environ.get("TFF_MAX_WORKERS")
    if env_tff:
        try:
            return max(1, int(env_tff.strip()))
        except ValueError:
            pass

    if config is not None:
        cfg_workers = getattr(config, "workers", None)
        if cfg_workers is not None:
            try:
                return max(1, int(cfg_workers))
            except ValueError:
                pass

    env_fork = os.environ.get("MAX_FORK_WORKERS")
    if env_fork:
        try:
            return max(1, int(env_fork.strip()))
        except ValueError:
            pass

    cpu_count = os.cpu_count() or 1
    return max(1, min(cpu_count, 8))


def _clean_sql_for_model(sql: str, provider: str | None = None) -> str:
    """Strip Jinja/Dataform/SQLMesh syntax noise for AST parsing."""
    cleaned = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
    cleaned = clean_dataform_for_parsing(cleaned)
    cleaned = clean_jinja_for_parsing(cleaned, provider=provider)
    return cleaned


def _worker_parse_model_sql(
    task: tuple[str, str, str, str | None, bool],
) -> tuple[str, exp.Expression | None]:
    """Top-level worker function for parsing a model SQL query into an AST."""
    model_name, cleaned_sql, dialect, cache_dir_str, cache_enabled = task
    cache_dir = Path(cache_dir_str) if cache_dir_str else None
    parsed = parse_sql_with_cache(
        cleaned_sql,
        dialect=dialect,
        cache_dir=cache_dir,
        enabled=cache_enabled,
    )
    return model_name, parsed


def precompute_model_asts(
    models: dict[str, ModelRepresentation],
    project_root: Path | None = None,
    config: FitnessFunctionsConfig | None = None,
    max_workers: int | None = None,
) -> None:
    """Parse and populate AST expressions for models in parallel using disk cache."""
    cache_enabled = is_cache_enabled(config)
    custom_cache = getattr(config, "cache_dir", None) if config else None
    cache_dir = get_ast_cache_dir(project_root, custom_dir=custom_cache) if cache_enabled else None

    tasks: list[tuple[str, str, str, str | None, bool]] = []

    for name, model in models.items():
        if model.expression is not None:
            continue
        if model.is_external or model.is_symbolic:
            continue

        try:
            sql = read_model_sql(model, project_root=project_root)
        except Exception as exc:
            logger.warning("Failed to read SQL for model '%s': %s", name, exc)
            continue

        if not sql or not sql.strip():
            continue

        cleaned_sql = _clean_sql_for_model(sql, provider=model.provider)
        if not cleaned_sql:
            continue

        # Fast in-process disk cache check
        if cache_enabled and cache_dir is not None:
            cache_key = compute_ast_cache_key(cleaned_sql, model.dialect)
            cached_ast = get_cached_ast(cache_key, cache_dir=cache_dir)
            if cached_ast is not None:
                model.expression = cached_ast
                continue

        tasks.append((
            name,
            cleaned_sql,
            model.dialect,
            str(cache_dir) if cache_dir else None,
            cache_enabled,
        ))

    if not tasks:
        return

    workers = get_max_workers(config=config, override=max_workers)
    if workers <= 1 or len(tasks) <= 2:
        for task in tasks:
            m_name, expr = _worker_parse_model_sql(task)
            if expr is not None and m_name in models:
                models[m_name].expression = expr
        return

    try:
        pool_size = min(workers, len(tasks))
        with ProcessPoolExecutor(max_workers=pool_size) as executor:
            chunksize = max(1, len(tasks) // (pool_size * 4))
            for m_name, expr in executor.map(_worker_parse_model_sql, tasks, chunksize=chunksize):
                if expr is not None and m_name in models:
                    models[m_name].expression = expr
    except Exception as exc:
        logger.debug("ProcessPoolExecutor encountered an issue (%s), falling back to sequential parsing", exc)
        for task in tasks:
            m_name, expr = _worker_parse_model_sql(task)
            if expr is not None and m_name in models:
                models[m_name].expression = expr
 
 
batch_parse_ast_in_parallel = precompute_model_asts


def _extract_model_findings(
    rule_cls: type[Rule],
    model: ModelRepresentation,
    violation: RuleViolation | None,
    severity: Severity,
    finding_check: str,
) -> list[LintFinding]:
    from tff.core.report import LintFinding
    from tff.core.utils.paths import model_path_relative

    if not violation:
        return []

    findings: list[LintFinding] = []
    msgs = violation.violation_msg
    if isinstance(msgs, str):
        msgs = [msgs]

    is_sql_complexity = (
        finding_check in ("sqlcomplexity", "sql_complexity")
        or getattr(rule_cls, "name", "") == "sqlcomplexity"
        or rule_cls.__name__ == "SqlComplexity"
    )

    for msg in msgs:
        model_label = f"{model.name}: "
        clean_msg = msg.removeprefix(model_label)
        if is_sql_complexity:
            parts = [p.strip() for p in clean_msg.split(";") if p.strip()]
            for part in parts:
                part_severity = severity
                if part.startswith("WARN:"):
                    part_severity = "warning"
                elif part.startswith("FAIL:"):
                    part_severity = "error" if severity == "error" else severity
                findings.append(
                    LintFinding(
                        check=finding_check,
                        severity=part_severity,
                        model=model.name,
                        path=model_path_relative(model),
                        message=part,
                    )
                )
        else:
            findings.append(
                LintFinding(
                    check=finding_check,
                    severity=severity,
                    model=model.name,
                    path=model_path_relative(model),
                    message=clean_msg,
                )
            )
    return findings


def _create_rule_execution_error_finding(
    model: ModelRepresentation,
    rule_name: str,
    exc: Exception,
) -> LintFinding:
    from tff.core.report import LintFinding
    from tff.core.utils.paths import model_path_relative

    err_msg = getattr(exc, "message", None) or str(exc) or exc.__class__.__name__

    return LintFinding(
        check="rule_execution_error",
        severity="error",
        model=model.name,
        path=model_path_relative(model),
        message=f"Rule '{rule_name}' failed to evaluate: {err_msg}",
    )


def _check_models_batch(
    args: tuple[type[Rule], Any, list[ModelRepresentation], Severity, str],
) -> list[LintFinding]:
    rule_cls, config, model_batch, severity, finding_check = args
    rule_name = finding_check or getattr(rule_cls, "name", rule_cls.__name__.lower())
    try:
        rule = rule_cls(config=config)
    except Exception as exc:
        logger.warning(
            "Rule '%s' failed to instantiate: %s",
            rule_name,
            exc,
            exc_info=True,
        )
        return [
            _create_rule_execution_error_finding(m, rule_name, exc)
            for m in model_batch
        ]

    findings: list[LintFinding] = []
    for model in model_batch:
        try:
            violation = rule.check_model(model)
            findings.extend(
                _extract_model_findings(
                    rule_cls=rule_cls,
                    model=model,
                    violation=violation,
                    severity=severity,
                    finding_check=finding_check,
                )
            )
        except Exception as exc:
            logger.warning(
                "Rule '%s' failed while evaluating model '%s': %s",
                rule_name,
                model.name,
                exc,
                exc_info=True,
            )
            findings.append(
                _create_rule_execution_error_finding(model, rule_name, exc)
            )
    return findings


def _check_single_model(
    args: tuple[type[Rule], Any, ModelRepresentation, Severity, str],
) -> list[LintFinding]:
    rule_cls, config, model, severity, finding_check = args
    return _check_models_batch((rule_cls, config, [model], severity, finding_check))


def run_parallel_model_rule(
    rule_cls: type[Rule],
    models: list[ModelRepresentation],
    severity: Severity = "error",
    check_name: str | None = None,
    config: FitnessFunctionsConfig | None = None,
    max_workers: int | None = None,
    chunk_size: int | None = None,
) -> list[LintFinding]:
    """Execute a single model rule across models, parallelizing across threads if beneficial."""
    finding_check = check_name or getattr(rule_cls, "name", rule_cls.__name__.lower())
    eligible_models = [m for m in models if not m.is_external and not m.is_symbolic]

    if not eligible_models:
        return []

    workers = get_max_workers(config=config, override=max_workers)
    if workers <= 1 or len(eligible_models) <= 20:
        findings: list[LintFinding] = []
        try:
            rule = rule_cls(config=config)
        except Exception as exc:
            logger.warning(
                "Rule '%s' failed to instantiate: %s",
                finding_check,
                exc,
                exc_info=True,
            )
            return [
                _create_rule_execution_error_finding(m, finding_check, exc)
                for m in eligible_models
            ]

        for model in eligible_models:
            try:
                violation = rule.check_model(model)
                findings.extend(
                    _extract_model_findings(
                        rule_cls=rule_cls,
                        model=model,
                        violation=violation,
                        severity=severity,
                        finding_check=finding_check,
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Rule '%s' failed while evaluating model '%s': %s",
                    finding_check,
                    model.name,
                    exc,
                    exc_info=True,
                )
                findings.append(
                    _create_rule_execution_error_finding(model, finding_check, exc)
                )
        return findings

    # Parallelize model rule execution using thread pool
    pool_size = min(workers, len(eligible_models))
    if chunk_size is None or chunk_size <= 0:
        env_chunk = os.environ.get("TFF_CHUNK_SIZE")
        if env_chunk:
            try:
                chunk_size = max(1, int(env_chunk.strip()))
            except ValueError:
                chunk_size = None

    if chunk_size is None or chunk_size <= 0:
        chunk_size = max(1, min(100, len(eligible_models) // (pool_size * 4)))

    batches = [
        eligible_models[i : i + chunk_size]
        for i in range(0, len(eligible_models), chunk_size)
    ]
    tasks = [
        (rule_cls, config, batch, severity, finding_check)
        for batch in batches
    ]
    all_findings: list[LintFinding] = []
    with ThreadPoolExecutor(max_workers=pool_size) as executor:
        for res in executor.map(_check_models_batch, tasks):
            all_findings.extend(res)

    return all_findings
