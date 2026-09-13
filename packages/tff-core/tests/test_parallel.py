"""Unit tests for tff.core.parallel worker pool utilities."""

from pathlib import Path
from unittest.mock import patch
import pytest
import sqlglot.expressions as exp

from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.parallel import (
    _clean_sql_for_model,
    get_max_workers,
    precompute_model_asts,
    run_parallel_model_rule,
)
from tff.core.rules.base import Rule, RuleViolation


class DummyBanFooRule(Rule):
    name = "dummy_ban_foo"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        if "foo" in model.name:
            return RuleViolation(
                violation_msg=f"{model.name}: model name contains foo",
            )
        return None


def test_get_max_workers(monkeypatch: pytest.MonkeyPatch):
    # 1. Override argument
    assert get_max_workers(override=4) == 4
    assert get_max_workers(override=0) == 1

    # Clear env vars
    monkeypatch.delenv("TFF_MAX_WORKERS", raising=False)
    monkeypatch.delenv("MAX_FORK_WORKERS", raising=False)

    # 2. Config workers
    cfg = FitnessFunctionsConfig(workers=3)
    assert get_max_workers(config=cfg) == 3

    # Config workers invalid value handled gracefully
    cfg_invalid = FitnessFunctionsConfig()
    cfg_invalid.__dict__["workers"] = "invalid"
    assert get_max_workers(config=cfg_invalid) >= 1

    # 3. TFF_WORKERS / TFF_MAX_WORKERS env var
    monkeypatch.setenv("TFF_WORKERS", "6")
    assert get_max_workers() == 6
    monkeypatch.setenv("TFF_WORKERS", "invalid")
    assert get_max_workers() >= 1
    monkeypatch.delenv("TFF_WORKERS")

    monkeypatch.setenv("TFF_MAX_WORKERS", "5")
    assert get_max_workers() == 5
    monkeypatch.setenv("TFF_MAX_WORKERS", "invalid")
    assert get_max_workers() >= 1

    # 4. MAX_FORK_WORKERS env var
    monkeypatch.delenv("TFF_MAX_WORKERS")
    monkeypatch.setenv("MAX_FORK_WORKERS", "2")
    assert get_max_workers() == 2
    monkeypatch.setenv("MAX_FORK_WORKERS", "bad")
    assert get_max_workers() >= 1

    # 5. Default
    monkeypatch.delenv("MAX_FORK_WORKERS")
    default_workers = get_max_workers()
    assert 1 <= default_workers <= 8


def test_clean_sql_for_model():
    sql = "MODEL (name my_model); SELECT * FROM ref('raw_data') WHERE x > 0;"
    cleaned = _clean_sql_for_model(sql)
    assert "MODEL" not in cleaned
    assert "WHERE x > 0" in cleaned


def test_precompute_model_asts_sequential_and_filters(tmp_path: Path):
    # Models to test filtering and sequential parsing
    sql_file = tmp_path / "model_file.sql"
    sql_file.write_text("SELECT 1 AS from_file", encoding="utf-8")

    m1 = ModelRepresentation(
        name="m1",
        path="m1.sql",
        dialect="duckdb",
        query="SELECT 1",
    )
    m_already_parsed = ModelRepresentation(
        name="m_already",
        path="m_already.sql",
        dialect="duckdb",
        expression=exp.Literal.number(42),
    )
    m_external = ModelRepresentation(
        name="m_ext",
        path="ext.sql",
        dialect="duckdb",
        is_external=True,
        query="SELECT 1",
    )
    m_symbolic = ModelRepresentation(
        name="m_sym",
        path="sym.sql",
        dialect="duckdb",
        is_symbolic=True,
        query="SELECT 1",
    )
    m_from_path = ModelRepresentation(
        name="m_file",
        path=str(sql_file),
        dialect="duckdb",
        query=None,
    )
    m_nonexistent = ModelRepresentation(
        name="m_nonexistent",
        path="nonexistent_path_xyz.sql",
        dialect="duckdb",
        query=None,
    )
    m_empty_path = ModelRepresentation(
        name="m_empty_path",
        path="",
        dialect="duckdb",
        query=None,
    )
    m_empty_sql = ModelRepresentation(
        name="m_empty_sql",
        path="empty.sql",
        dialect="duckdb",
        query="   ",
    )
    m_model_block_only = ModelRepresentation(
        name="m_model_block_only",
        path="m_block.sql",
        dialect="duckdb",
        query="MODEL (name empty_model);",
    )

    rel_dir = tmp_path / "models" / "staging"
    rel_dir.mkdir(parents=True, exist_ok=True)
    rel_file = rel_dir / "rel_model.sql"
    rel_file.write_text("SELECT 99 AS val", encoding="utf-8")
    m_rel = ModelRepresentation(
        name="m_rel",
        path="models/staging/rel_model.sql",
        dialect="duckdb",
        query=None,
    )

    models = {
        "m1": m1,
        "m_already": m_already_parsed,
        "m_ext": m_external,
        "m_sym": m_symbolic,
        "m_file": m_from_path,
        "m_nonexistent": m_nonexistent,
        "m_empty_path": m_empty_path,
        "m_empty_sql": m_empty_sql,
        "m_block": m_model_block_only,
        "m_rel": m_rel,
    }

    precompute_model_asts(models, project_root=tmp_path, max_workers=1)

    assert m1.expression is not None
    assert m_already_parsed.expression == exp.Literal.number(42)
    assert m_external.expression is None
    assert m_symbolic.expression is None
    assert m_from_path.expression is not None
    assert m_rel.expression is not None
    assert m_nonexistent.expression is None
    assert m_empty_path.expression is None
    assert m_empty_sql.expression is None
    assert m_model_block_only.expression is None


def test_precompute_model_asts_read_ioerror(tmp_path: Path):
    bad_file = tmp_path / "bad.sql"
    bad_file.write_text("SELECT 1", encoding="utf-8")
    m_bad = ModelRepresentation(
        name="m_bad",
        path=str(bad_file),
        dialect="duckdb",
        query=None,
    )

    with patch("pathlib.Path.read_text", side_effect=IOError("Read error")):
        precompute_model_asts({"m_bad": m_bad}, project_root=tmp_path, max_workers=1)
        assert m_bad.expression is None


def test_precompute_model_asts_cache_hit(tmp_path: Path):
    cache_dir = tmp_path / ".tff_cache" / "ast"
    from tff.core.ast_cache import parse_sql_with_cache

    sql = "SELECT id FROM cached_table"
    dialect = "duckdb"
    # Pre-populate cache
    parse_sql_with_cache(sql, dialect, cache_dir=cache_dir)

    model = ModelRepresentation(
        name="cached_model",
        path="m.sql",
        dialect=dialect,
        query=sql,
    )
    models = {"cached_model": model}

    # Should hit cache without worker tasks
    precompute_model_asts(models, project_root=tmp_path, max_workers=1)
    assert model.expression is not None


def test_precompute_model_asts_parallel_pool(tmp_path: Path):
    # Multiple models to trigger parallel pool execution (len > 2 and workers > 1)
    models = {}
    for i in range(5):
        models[f"model_{i}"] = ModelRepresentation(
            name=f"model_{i}",
            path=f"models/m_{i}.sql",
            dialect="duckdb",
            query=f"SELECT {i} AS val, name FROM table_{i}",
        )

    precompute_model_asts(models, project_root=tmp_path, max_workers=2)

    for i in range(5):
        assert models[f"model_{i}"].expression is not None
        assert isinstance(models[f"model_{i}"].expression, exp.Expression)


def test_precompute_model_asts_parallel_pool_fallback(tmp_path: Path):
    models = {}
    for i in range(4):
        models[f"model_{i}"] = ModelRepresentation(
            name=f"model_{i}",
            path=f"models/m_{i}.sql",
            dialect="duckdb",
            query=f"SELECT {i} AS val",
        )

    # Simulate ProcessPoolExecutor failure to trigger graceful fallback
    with patch(
        "tff.core.parallel.ProcessPoolExecutor",
        side_effect=RuntimeError("Process pool unavailable"),
    ):
        precompute_model_asts(models, project_root=tmp_path, max_workers=2)

    for i in range(4):
        assert models[f"model_{i}"].expression is not None


def test_run_parallel_model_rule_sequential():
    # Empty models
    assert run_parallel_model_rule(DummyBanFooRule, []) == []

    # Sequential rule execution (<= 20 models)
    models = [
        ModelRepresentation(name="foo_model", path="models/foo.sql", dialect="duckdb"),
        ModelRepresentation(name="bar_model", path="models/bar.sql", dialect="duckdb"),
        ModelRepresentation(name="external_foo", path="ext.sql", dialect="duckdb", is_external=True),
    ]

    findings = run_parallel_model_rule(
        rule_cls=DummyBanFooRule,
        models=models,
        severity="error",
        check_name="dummy_ban_foo",
        max_workers=1,
    )
    assert len(findings) == 1
    assert findings[0].model == "foo_model"
    assert findings[0].message == "model name contains foo"


def test_run_parallel_model_rule_multithreaded():
    # > 20 models to trigger ThreadPoolExecutor
    models = []
    for i in range(25):
        name = f"foo_{i}" if i % 2 == 0 else f"bar_{i}"
        models.append(
            ModelRepresentation(
                name=name,
                path=f"models/{name}.sql",
                dialect="duckdb",
            )
        )

    findings = run_parallel_model_rule(
        rule_cls=DummyBanFooRule,
        models=models,
        severity="error",
        check_name="dummy_ban_foo",
        max_workers=2,
    )
    # Even indices (0, 2, 4, ..., 24) = 13 models contain 'foo'
    assert len(findings) == 13
    assert all(f.check == "dummy_ban_foo" for f in findings)


def test_precompute_model_asts_custom_cache_dir(tmp_path: Path):
    custom_dir = tmp_path / "custom_cache"
    cfg = FitnessFunctionsConfig(cache_dir=str(custom_dir))

    model = ModelRepresentation(
        name="custom_cached_model",
        path="m.sql",
        dialect="duckdb",
        query="SELECT 123",
    )
    precompute_model_asts(
        {"custom_cached_model": model},
        project_root=tmp_path,
        config=cfg,
        max_workers=1,
    )
    assert model.expression is not None
    assert (custom_dir / "ast").exists()
