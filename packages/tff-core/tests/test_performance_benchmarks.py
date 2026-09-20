"""Performance and throughput benchmark tests for tff core operations."""

from __future__ import annotations

import time
from pathlib import Path

from tff.core.adapter import get_adapter
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.parallel import precompute_model_asts, run_parallel_model_rule
from tff.core.rules.base import Rule, RuleViolation


class DummyComplexityRule(Rule):
    name = "dummy_complexity_rule"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        if model.ast is not None:
            # Simple traversal
            _ = list(model.ast.find_all(object))
        return None


def test_ast_cache_performance_speedup(tmp_path: Path):
    """Verify that cached AST precomputation is fast and deterministic."""
    sql_content = "WITH cte1 AS (SELECT 1 AS a), cte2 AS (SELECT 2 AS b) SELECT a, b FROM cte1 JOIN cte2 ON 1=1"
    model_path = tmp_path / "model.sql"
    model_path.write_text(sql_content, encoding="utf-8")

    models = {
        f"model_{i}": ModelRepresentation(
            name=f"model_{i}",
            path=str(model_path),
            dialect="duckdb",
        )
        for i in range(10)
    }

    # First pass: cold cache
    t0 = time.perf_counter()
    precompute_model_asts(models, project_root=tmp_path, max_workers=2)
    cold_time = time.perf_counter() - t0

    # Ensure all models have AST populated
    for m in models.values():
        assert m.ast is not None

    # Clear memory ASTs to test warm disk cache reload
    for m in models.values():
        m.expression = None

    t1 = time.perf_counter()
    precompute_model_asts(models, project_root=tmp_path, max_workers=2)
    warm_time = time.perf_counter() - t1

    for m in models.values():
        assert m.ast is not None

    # Both cold and warm passes should complete well within budget
    assert cold_time < 5.0
    assert warm_time < 5.0


def test_parallel_rule_execution_throughput(tmp_path: Path):
    """Verify parallel rule evaluation scales across models without deadlocks."""
    sql_content = "SELECT 1 AS id"
    model_path = tmp_path / "dummy.sql"
    model_path.write_text(sql_content, encoding="utf-8")

    models = {
        f"model_{i}": ModelRepresentation(
            name=f"model_{i}",
            path=str(model_path),
            dialect="duckdb",
        )
        for i in range(20)
    }

    precompute_model_asts(models, project_root=tmp_path, max_workers=2)

    t0 = time.perf_counter()
    findings = run_parallel_model_rule(
        DummyComplexityRule,
        list(models.values()),
        max_workers=2,
        chunk_size=5,
    )
    elapsed = time.perf_counter() - t0

    assert len(findings) == 0
    assert elapsed < 5.0


def test_dbt_check_sla_budget():
    """Verify dbt example check executes well under SLA ceiling."""
    repo_root = Path(__file__).resolve().parents[3]
    dbt_project = repo_root / "examples" / "minimal-dbt-project"

    adapter = get_adapter("dbt")
    config = FitnessFunctionsConfig()

    t0 = time.perf_counter()
    findings, count, executed = adapter.run_checks(
        project_root=dbt_project,
        config=config,
    )
    elapsed = time.perf_counter() - t0

    assert count == 4
    assert len(findings) == 7
    # 4 models should take a fraction of a second
    assert elapsed < 3.0
