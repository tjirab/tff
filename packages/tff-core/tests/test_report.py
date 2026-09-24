"""Tests for lint report check filtering."""

from tff.core.report import _summary_check_names


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

    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
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
        group_by="connascence",
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

    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
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
    assert "Issues by Model" in output
    assert "Repository-level issues" in output
    assert "marts.users" in output
    assert "core.orders" in output
    assert "Connascence of Name (CoN)" not in output


def test_render_lint_report_groups_by_connascence_cop() -> None:
    from rich.console import Console

    from tff.core.report import LintFinding, render_lint_report

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
        group_by="connascence",
    )

    assert success is False

    output = console.export_text()
    assert "Connascence of Position (CoP)" in output
    assert "marts.users" in output


def test_render_lint_report_warnings_and_multiline() -> None:
    from rich.console import Console

    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
            severity="warning",
            message="SELECT *\nis prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
        LintFinding(
            check="schema_contracts",
            severity="warning",
            message="some contract\nviolation",
            model=None,
            path=None,
        ),
    ]

    success = render_lint_report(
        findings,
        models_checked=2,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="connascence",
    )
    assert success is True

    output = console.export_text()
    assert "LINT WARNINGS" in output
    assert "SELECT *" in output
    assert "is prohibited." in output
    assert "Repository-level" in output

    console_model = Console(record=True, width=120)
    success_model = render_lint_report(
        findings,
        models_checked=2,
        executed_checks=["sqlmesh"],
        console=console_model,
        group_by="model",
    )
    assert success_model is True
    output_model = console_model.export_text()
    assert "Issues by Model" in output_model
    assert "SELECT *" in output_model
    assert "is prohibited." in output_model


def test_format_check_cell_with_known_check() -> None:
    from tff.core.registry import registry
    from tff.core.report import _format_check_cell

    cell = _format_check_cell("banselectstar")
    assert cell.plain == "No SELECT *"
    docs_url = registry.get_docs_url("banselectstar")
    assert docs_url is not None
    assert f"link {docs_url}" in str(cell.style)


def test_format_check_cell_with_unknown_check() -> None:
    from tff.core.report import _format_check_cell

    cell = _format_check_cell("custom_unknown_check")
    assert cell.plain == "custom_unknown_check"
    assert cell.style == "bold"


def test_append_check_tag_with_known_check() -> None:
    from rich.text import Text

    from tff.core.registry import registry
    from tff.core.report import _append_check_tag

    text = Text("Issue message ")
    _append_check_tag(text, "banselectstar")
    assert text.plain == "Issue message (banselectstar)"
    span = text.spans[0]
    assert span.start == len("Issue message ")
    assert span.end == len("Issue message (banselectstar)")
    docs_url = registry.get_docs_url("banselectstar")
    assert docs_url is not None
    assert f"link {docs_url}" in str(span.style)


def test_append_check_tag_with_unknown_check() -> None:
    from rich.text import Text

    from tff.core.report import _append_check_tag

    text = Text("Issue message ")
    _append_check_tag(text, "custom_unknown_check")
    assert text.plain == "Issue message (custom_unknown_check)"
    span = text.spans[0]
    assert span.style == "dim"


def test_render_lint_report_hyperlinks_in_terminal_output() -> None:
    from rich.console import Console

    from tff.core.registry import registry
    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
        LintFinding(
            check="layer_integrity",
            severity="error",
            message="Repo level architecture failure.",
            model=None,
            path=None,
        ),
        LintFinding(
            check="unknown_rule",
            severity="warning",
            message="Unknown warning.",
            model=None,
            path=None,
        ),
    ]

    render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="model",
    )

    docs_url = registry.get_docs_url("banselectstar")
    assert docs_url is not None
    arch_docs_url = registry.get_docs_url("layer_integrity")
    assert arch_docs_url is not None
    # Rich export_html renders OSC-8 hyperlinks as HTML <a> anchors
    html_output = console.export_html(clear=False)
    assert f'href="{docs_url}"' in html_output
    assert f'href="{arch_docs_url}"' in html_output
    # Plain text export should not leak URL markup
    text_output = console.export_text()
    assert "https://tff.readthedocs.io" not in text_output
    assert "(banselectstar)" in text_output
    assert "(layer_integrity)" in text_output
    assert "(unknown_rule)" in text_output


def test_render_lint_report_connascence_grouping_hyperlinks() -> None:
    from rich.console import Console

    from tff.core.registry import registry
    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
    ]

    render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="connascence",
    )

    docs_url = registry.get_docs_url("banselectstar")
    assert docs_url is not None
    html_output = console.export_html(clear=False)
    assert f'href="{docs_url}"' in html_output
    text_output = console.export_text()
    assert "https://tff.readthedocs.io" not in text_output
    assert "(banselectstar)" in text_output



