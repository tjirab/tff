"""Tests for lint report check filtering."""

from sqlmesh_ff.report import _summary_check_names


def test_summary_shows_only_executed_architectural_check() -> None:
    names = _summary_check_names(["layer_integrity"], {})
    assert names == ["layer_integrity"]


def test_summary_expands_sqlmesh_when_no_findings() -> None:
    names = _summary_check_names(["sqlmesh"], {})
    assert set(names) == {"classificationmacros", "sqlcomplexity"}


def test_summary_uses_sqlmesh_finding_rule_names() -> None:
    by_check = {"nomissinggrain": {"error": 2, "warning": 0}}
    names = _summary_check_names(["sqlmesh"], by_check)
    assert names == ["nomissinggrain"]


def test_summary_full_run_includes_architectural_and_sqlmesh() -> None:
    executed = [
        "sqlmesh",
        "layer_integrity",
        "custom_exclusions",
        "schema_contracts",
        "dependency_graph",
    ]
    names = _summary_check_names(executed, {})
    assert set(names) == {
        "layer_integrity",
        "custom_exclusions",
        "schema_contracts",
        "dependency_graph",
        "classificationmacros",
        "sqlcomplexity",
    }


def test_render_lint_report_groups_by_connascence() -> None:
    from rich.console import Console

    from sqlmesh_ff.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="noselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
        LintFinding(
            check="classificationmacros",
            severity="warning",
            message="Inline CASE defines product_type",
            model="core.orders",
            path="models/core/orders.sql",
        ),
        LintFinding(
            check="layer_integrity",
            severity="error",
            message="depends on downstream model",
            model="core.orders",
            path="models/core/orders.sql",
        ),
        LintFinding(
            check="schema_contracts",
            severity="error",
            message="some contract violation",
            model=None,
            path=None,
        ),
    ]

    success = render_lint_report(
        findings,
        models_checked=2,
        executed_checks=["sqlmesh", "layer_integrity"],
        console=console,
    )

    assert success is False

    output = console.export_text()
    assert "Connascence of Name (CoN)" in output
    assert "Connascence of Meaning (CoM)" in output
    assert "Dynamic Coupling & DAG Structure" in output
    assert "marts.users" in output
    assert "core.orders" in output
    assert "Repository-level" in output


def test_render_lint_report_groups_by_model() -> None:
    from rich.console import Console

    from sqlmesh_ff.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="noselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
        LintFinding(
            check="classificationmacros",
            severity="warning",
            message="Inline CASE defines product_type",
            model="core.orders",
            path="models/core/orders.sql",
        ),
        LintFinding(
            check="schema_contracts",
            severity="error",
            message="some contract violation",
            model=None,
            path=None,
        ),
    ]

    success = render_lint_report(
        findings,
        models_checked=2,
        executed_checks=["sqlmesh", "layer_integrity"],
        console=console,
        group_by="model",
    )

    assert success is False

    output = console.export_text()
    assert "Issues by model" in output
    assert "Repository-level issues" in output
    assert "marts.users" in output
    assert "core.orders" in output
    assert "Connascence of Name (CoN)" not in output


def test_render_lint_report_groups_by_connascence_cop() -> None:
    from rich.console import Console

    from sqlmesh_ff.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="error",
            message="Positional GROUP BY '1' found.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
    ]

    success = render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
    )

    assert success is False

    output = console.export_text()
    assert "Connascence of Position (CoP)" in output
    assert "marts.users" in output

