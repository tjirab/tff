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


def test_normalize_model_name() -> None:
    from tff.core.report import normalize_model_name

    assert normalize_model_name("model.my_project.dim_users") == "dim_users"
    assert normalize_model_name("source.my_project.raw_users") == "raw_users"
    assert normalize_model_name("seed.my_project.country_codes") == "country_codes"
    assert normalize_model_name("snapshot.my_project.orders_snapshot") == "orders_snapshot"
    assert normalize_model_name('"model"."my_project"."dim_users"') == "dim_users"
    assert normalize_model_name("sqlmesh_example.dim_users") == "sqlmesh_example.dim_users"
    assert normalize_model_name("catalog.sqlmesh_example.dim_users") == "sqlmesh_example.dim_users"
    assert normalize_model_name("dim_users") == "dim_users"


def test_render_lint_report_unifies_model_headings_across_checks() -> None:
    from rich.console import Console

    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="dependency_graph",
            severity="error",
            message="fan_out=5 (fail>2) — high blast-radius hub model",
            model="dbt_example.dim_users",
            path="models/core/dim_users.sql",
        ),
        LintFinding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="dim_users",
            path="models/core/dim_users.sql",
        ),
        LintFinding(
            check="materialization_depth",
            severity="warning",
            message="View nesting depth is 3",
            model="model.dbt_example.dim_users",
            path="models/core/dim_users.sql",
        ),
    ]

    success = render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh", "dependency_graph"],
        console=console,
        group_by="model",
    )

    assert success is False
    output = console.export_text()

    # The canonical heading ● dim_users should appear exactly once
    assert output.count("● dim_users") == 1
    # Qualified model prefix should not appear as a separate heading
    assert "● dbt_example.dim_users" not in output
    assert "● model.dbt_example.dim_users" not in output
    # All 3 findings should be present under the single heading
    assert "fan_out=5" in output
    assert "SELECT * is prohibited" in output
    assert "View nesting depth is 3" in output


def test_render_lint_report_model_grouping_edge_cases() -> None:
    from rich.console import Console

    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        # 1. Finding with path only (no model name)
        LintFinding(
            check="banselectstar",
            severity="error",
            message="No select star",
            model=None,
            path="models/staging/stg_only_path.sql",
        ),
        # 2. Finding with model name only first (no path)
        LintFinding(
            check="sqlcomplexity",
            severity="warning",
            message="High complexity",
            model="orders",
            path=None,
        ),
        # 3. Subsequent finding with path that matches the previous model name by stem
        LintFinding(
            check="banselectstar",
            severity="error",
            message="No select star in orders",
            model="orders",
            path="models/marts/orders.sql",
        ),
        # 4. Finding with path first
        LintFinding(
            check="banselectstar",
            severity="error",
            message="No select star in customers",
            model="customers",
            path="models/marts/customers.sql",
        ),
        # 5. Subsequent finding with model name only that matches by norm_name
        LintFinding(
            check="sqlcomplexity",
            severity="warning",
            message="High complexity in customers",
            model="customers",
            path=None,
        ),
        # 6. Model name only first
        LintFinding(
            check="nomissingowner",
            severity="error",
            message="Missing owner",
            model="reports",
            path=None,
        ),
        # 7. Subsequent finding with no model name, but path stem matches previous model
        LintFinding(
            check="banselectstar",
            severity="error",
            message="No select star in reports",
            model=None,
            path="models/marts/reports.sql",
        ),
    ]

    success = render_lint_report(
        findings,
        models_checked=4,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="model",
    )

    assert success is False
    output = console.export_text()
    assert "● stg_only_path" in output
    assert "● orders" in output
    assert "● customers" in output
    assert "● reports" in output
    assert output.count("● orders") == 1
    assert output.count("● customers") == 1
    assert output.count("● reports") == 1
    assert "models/marts/orders.sql" in output
    assert "models/marts/customers.sql" in output
    assert "models/marts/reports.sql" in output


def test_render_lint_report_multiline_finding_formatting() -> None:
    """Multi-line findings format cleanly with rule tag on line 1 and sub-bullets indented below."""
    from rich.console import Console
    from tff.core.report import LintFinding, render_lint_report

    multiline_msg = "another_user_model.sql does not match dim_users.sql:\n  - missing columns: api_request, bad_id\n  + extra columns: email_flag"
    findings = [
        LintFinding(
            check="schema_contracts",
            severity="error",
            message=multiline_msg,
            model=None,
            path=None,
        ),
        LintFinding(
            check="schema_contracts",
            severity="error",
            message=multiline_msg,
            model="user_model",
            path="models/marts/user_model.sql",
        ),
    ]

    console_model = Console(record=True, width=120)
    render_lint_report(findings, models_checked=2, executed_checks=["schema_contracts"], console=console_model, group_by="model")
    out_model = console_model.export_text()

    assert "another_user_model.sql does not match dim_users.sql: (schema_contracts)" in out_model
    assert "  - missing columns: api_request, bad_id" in out_model
    assert "  + extra columns: email_flag" in out_model

    console_cat = Console(record=True, width=120)
    render_lint_report(findings, models_checked=2, executed_checks=["schema_contracts"], console=console_cat, group_by="connascence")
    out_cat = console_cat.export_text()

    assert "another_user_model.sql does not match dim_users.sql: (schema_contracts)" in out_cat
    assert "  - missing columns: api_request, bad_id" in out_cat
    assert "  + extra columns: email_flag" in out_cat






