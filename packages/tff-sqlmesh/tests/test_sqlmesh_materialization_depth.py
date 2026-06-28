"""Integration tests for materialization depth check on SQLMesh."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from tff.core.config import ChecksConfig, FitnessFunctionsConfig, MaterializationDepthCheckConfig
from tff.sqlmesh.runner import run_all_checks


def test_sqlmesh_materialization_depth_integration():
    mock_context = MagicMock()

    # Create mock SQLMesh models:
    # model_a (table) -> model_b (view) -> model_c (view) -> model_d (view) -> model_e (view)
    kinds = []
    for is_view in [False, True, True, True, True]:
        k = MagicMock()
        k.is_symbolic = False
        k.name = "VIEW" if is_view else "FULL"
        k.is_view = is_view
        kinds.append(k)

    names = ["model_a", "model_b", "model_c", "model_d", "model_e"]
    deps = [set(), {"model_a"}, {"model_b"}, {"model_c"}, {"model_d"}]
    paths = [
        Path("models/model_a.sql"),
        Path("models/model_b.sql"),
        Path("models/model_c.sql"),
        Path("models/model_d.sql"),
        Path("models/model_e.sql"),
    ]

    models = {}
    for name, kind, dep, path in zip(names, kinds, deps, paths):
        m = MagicMock()
        m.name = name
        m.project = ""
        m.kind = kind
        m.depends_on = dep
        m._path = path
        m.dialect = "duckdb"
        m.columns_to_types = {}
        m.description = None
        m.owner = None
        m.grains = []
        m.audits = []
        models[name] = m

    mock_context.models = models

    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=True, max_depth_warn=2, max_depth_fail=3
            )
        )
    )

    findings, checked, selected = run_all_checks(
        context=mock_context, config=config, checks=["materialization_depth"]
    )

    assert "materialization_depth" in selected

    warns = [f for f in findings if f.severity == "warning"]
    errors = [f for f in findings if f.severity == "error"]

    assert len(warns) == 1
    assert warns[0].model == "model_d"

    assert len(errors) == 1
    assert errors[0].model == "model_e"
