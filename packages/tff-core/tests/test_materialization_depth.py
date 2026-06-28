"""Unit tests for materialization depth check."""

from __future__ import annotations

from tff.core.checks.materialization_depth import collect_materialization_depth_findings
from tff.core.config import FitnessFunctionsConfig, ChecksConfig, MaterializationDepthCheckConfig
from tff.core.model import ModelRepresentation


def test_materialization_depth_no_findings():
    models = {
        "model_a": ModelRepresentation(
            name="model_a",
            path="models/marts/model_a.sql",
            dialect="duckdb",
            materialized="table",
        ),
        "model_b": ModelRepresentation(
            name="model_b",
            path="models/marts/model_b.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"model_a"},
        ),
    }
    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=True, max_depth_warn=3, max_depth_fail=5
            )
        )
    )
    findings = collect_materialization_depth_findings(models, config)
    assert len(findings) == 0


def test_materialization_depth_warning_and_error():
    models = {
        "source": ModelRepresentation(
            name="source",
            path="models/sources/source.sql",
            dialect="duckdb",
            materialized="table",
        ),
        "view_1": ModelRepresentation(
            name="view_1",
            path="models/marts/view_1.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"source"},
        ),
        "view_2": ModelRepresentation(
            name="view_2",
            path="models/marts/view_2.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"view_1"},
        ),
        "view_3": ModelRepresentation(
            name="view_3",
            path="models/marts/view_3.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"view_2"},
        ),
        "view_4": ModelRepresentation(
            name="view_4",
            path="models/marts/view_4.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"view_3"},
        ),
        "view_5": ModelRepresentation(
            name="view_5",
            path="models/marts/view_5.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"view_4"},
        ),
    }
    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=True, max_depth_warn=3, max_depth_fail=4
            )
        )
    )
    findings = collect_materialization_depth_findings(models, config)

    warns = [f for f in findings if f.severity == "warning"]
    errors = [f for f in findings if f.severity == "error"]

    assert len(warns) == 1
    assert warns[0].model == "view_4"
    assert "View nesting depth is 4" in warns[0].message

    assert len(errors) == 1
    assert errors[0].model == "view_5"
    assert "View nesting depth is 5" in errors[0].message


def test_materialization_depth_layer_filtering():
    models = {
        "view_1": ModelRepresentation(
            name="view_1",
            path="models/sources/view_1.sql",
            dialect="duckdb",
            materialized="view",
        ),
        "view_2": ModelRepresentation(
            name="view_2",
            path="models/sources/view_2.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"view_1"},
        ),
    }
    # config skips sources layer by default for this check if we configure it to
    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=True,
                max_depth_warn=0,
                max_depth_fail=1,
                skip_layers=["sources"],
            )
        )
    )
    findings = collect_materialization_depth_findings(models, config)
    assert len(findings) == 0


def test_materialization_depth_cycle_protection():
    models = {
        "view_a": ModelRepresentation(
            name="view_a",
            path="models/marts/view_a.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"view_b"},
        ),
        "view_b": ModelRepresentation(
            name="view_b",
            path="models/marts/view_b.sql",
            dialect="duckdb",
            materialized="view",
            depends_on={"view_a"},
        ),
    }
    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=True, max_depth_warn=3, max_depth_fail=5
            )
        )
    )
    findings = collect_materialization_depth_findings(models, config)
    # Recursion doesn't loop infinitely and resolves depth safely (returns 0/1/2 but cycle doesn't crash)
    # The depth calculation with cycle protection will see:
    # get_view_depth("view_a") -> get_view_depth("view_b") -> get_view_depth("view_a") [detected cycle, returns 0]
    # So "view_b" returns 0 + 1 = 1, "view_a" returns 1 + 1 = 2. Neither exceeds warning threshold (3).
    assert len(findings) == 0


def test_materialization_depth_disabled():
    models = {
        "view_a": ModelRepresentation(
            name="view_a",
            path="models/marts/view_a.sql",
            dialect="duckdb",
            materialized="view",
        ),
    }
    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=False
            )
        )
    )
    findings = collect_materialization_depth_findings(models, config)
    assert len(findings) == 0

