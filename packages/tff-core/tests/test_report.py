from typing import Any
import pytest
from tff.core.report import LintFinding, _summary_check_names


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
    assert "TFF ARCHITECTURE AUDIT" in output
    assert "banselectstar" in output
    assert "classificationmacros" in output
    assert "layer_integrity" in output
    assert "schema_contracts" in output
    assert "models/marts/users.sql" in output
    assert "models/core/orders.sql" in output


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
    assert "TFF ARCHITECTURE AUDIT" in output
    assert "models/marts/users.sql" in output
    assert "models/core/orders.sql" in output
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
    assert "nopositionalgroupbyororderby" in output
    assert "position" in output
    assert "models/marts/users.sql" in output


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
    assert "WARN —" in output
    assert "SELECT *" in output
    assert "is prohibited." in output
    assert "models/marts/users.sql" in output

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
    assert "TFF ARCHITECTURE AUDIT" in output_model
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
    # Plain text export should not leak URL markup
    text_output = console.export_text()
    assert "https://tff.readthedocs.io" not in text_output
    assert "banselectstar" in text_output
    assert "layer_integrity" in text_output
    assert "unknown_rule" in text_output


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
    assert "banselectstar" in text_output


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

    assert "models/core/dim_users.sql" in output
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
    assert "stg_only_path" in output
    assert "orders" in output
    assert "customers" in output
    assert "reports" in output
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

    assert "another_user_model.sql does not match dim_users.sql:" in out_model
    assert "schema_contracts" in out_model
    assert "  - missing columns: api_request, bad_id" in out_model
    assert "  + extra columns: email_flag" in out_model

    console_cat = Console(record=True, width=120)
    render_lint_report(findings, models_checked=2, executed_checks=["schema_contracts"], console=console_cat, group_by="connascence")
    out_cat = console_cat.export_text()

    assert "another_user_model.sql does not match dim_users.sql:" in out_cat
    assert "schema_contracts" in out_cat
    assert "  - missing columns: api_request, bad_id" in out_cat
    assert "  + extra columns: email_flag" in out_cat


def test_render_lint_report_with_duration() -> None:
    from rich.console import Console
    from tff.core.report import render_lint_report

    console = Console(record=True, width=120)
    render_lint_report(
        [],
        models_checked=15,
        executed_checks=["rules"],
        console=console,
        duration=0.42,
    )
    output = console.export_text()
    assert "15 models" in output
    assert "0.42s" in output


def test_format_file_reference_without_line() -> None:
    from tff.core.report import _format_file_reference

    ref = _format_file_reference("models/core/dim_users.sql")
    assert ref.plain == "models/core/dim_users.sql"
    assert "link file://" in str(ref.style)


def test_format_file_reference_with_line() -> None:
    from tff.core.report import _format_file_reference

    ref = _format_file_reference("models/core/dim_users.sql", line=42)
    assert ref.plain == "models/core/dim_users.sql:42"
    assert "link file://" in str(ref.style)


def test_render_lint_report_model_view_shows_line_coordinates() -> None:
    """Findings with line info show 'path:line' prefix in model-grouped view."""
    from rich.console import Console

    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="dim_users",
            path="models/core/dim_users.sql",
            line=42,
        ),
        LintFinding(
            check="sqlcomplexity",
            severity="warning",
            message="High complexity score.",
            model="dim_users",
            path="models/core/dim_users.sql",
            line=None,
        ),
    ]

    render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="model",
    )

    output = console.export_text(clear=False)
    assert "42:1" in output
    assert "models/core/dim_users.sql" in output

    html_output = console.export_html(clear=False)
    assert "file://" in html_output


def test_render_lint_report_connascence_view_shows_line_coordinates() -> None:
    """Findings with line info show 'path:line' prefix in connascence-grouped view."""
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
            line=10,
        ),
    ]

    render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="connascence",
    )

    output = console.export_text(clear=False)
    assert "models/marts/users.sql:10" in output

    html_output = console.export_html(clear=False)
    assert "file://" in html_output


def test_render_lint_report_model_header_has_clickable_file_link() -> None:
    """Model header path is wrapped in an OSC 8 file:// hyperlink."""
    from rich.console import Console

    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="dim_users",
            path="models/core/dim_users.sql",
        ),
    ]

    render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="model",
    )

    output = console.export_text(clear=False)
    assert "models/core/dim_users.sql" in output

    html_output = console.export_html(clear=False)
    assert "file://" in html_output


def _make_finding(
    model: str | None = None,
    path: str | None = None,
    msg: str = "violation",
    check: str = "check_a",
) -> LintFinding:
    return LintFinding(check=check, severity="error", message=msg, model=model, path=path)


@pytest.mark.parametrize(
    "findings,expected_name,expected_path",
    [
        (
            [
                _make_finding(path="models/core/dim_users.sql"),
                _make_finding(model="dim_users"),
            ],
            "dim_users",
            "models/core/dim_users.sql",
        ),
        (
            [
                _make_finding(model="dim_users"),
                _make_finding(path="models/core/dim_users.sql"),
            ],
            "dim_users",
            "models/core/dim_users.sql",
        ),
        (
            [
                _make_finding(path="models/core/dim_users.sql"),
                _make_finding(model="analytics.dim_users"),
            ],
            "analytics.dim_users",
            "models/core/dim_users.sql",
        ),
        (
            [
                _make_finding(model="analytics.dim_users"),
                _make_finding(path="models/core/dim_users.sql"),
            ],
            "analytics.dim_users",
            "models/core/dim_users.sql",
        ),
    ],
)
def test_group_findings_by_model_order_independent(
    findings: list[Any], expected_name: str, expected_path: str
) -> None:
    from tff.core.report import group_findings_by_model

    groups, repo = group_findings_by_model(findings)
    assert len(groups) == 1
    assert groups[0]["name"] == expected_name
    assert groups[0]["path"] == expected_path
    assert len(groups[0]["findings"]) == len(findings)
    assert len(repo) == 0


def test_group_findings_by_model_bridge_merges_disjoint_and_prevents_stale_lookup() -> None:
    """Findings that bridge disjoint groups merge them and re-point path_to_key without KeyError."""
    from tff.core.report import group_findings_by_model

    findings = [
        _make_finding(model="users", path="models/staging/users.sql", msg="Staging model"),
        _make_finding(model=None, path="models/other/users.sql", msg="Other path"),
        _make_finding(model="users", path="models/other/users.sql", msg="Bridge"),
        _make_finding(model=None, path="models/staging/users.sql", msg="Subsequent staging"),
    ]
    groups, repo = group_findings_by_model(findings)
    assert len(groups) == 1
    assert len(groups[0]["findings"]) == 4
    assert len(repo) == 0


def test_group_findings_by_model_same_stem_different_folders_remain_isolated() -> None:
    """Models with same stem in different folders remain distinct groups."""
    from tff.core.report import group_findings_by_model

    findings = [
        _make_finding(model="staging.users", path="models/staging/users.sql"),
        _make_finding(model="marts.users", path="models/marts/users.sql"),
        _make_finding(model="staging.users", path=None),
        _make_finding(model="marts.users", path=None),
    ]
    groups, _ = group_findings_by_model(findings)
    assert len(groups) == 2
    assert {g["name"] for g in groups} == {"staging.users", "marts.users"}


def test_render_lint_report_model_grouping_e2e() -> None:
    """End-to-end integration test verifying Rich console output with model header."""
    from rich.console import Console
    from tff.core.report import render_lint_report

    console = Console(record=True, width=120)
    findings = [
        _make_finding(path="models/core/dim_users.sql", msg="Column type mismatch."),
        _make_finding(model="dim_users", msg="SELECT * prohibited."),
    ]
    render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="model",
    )
    output = console.export_text()
    assert "models/core/dim_users.sql" in output
    assert "Column type mismatch." in output
    assert "SELECT * prohibited." in output


def test_render_lint_report_tree_branches_and_footer() -> None:
    """Verify tree formatting with branch symbols and fixable footer."""
    from rich.console import Console
    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="dim_users",
            path="models/core/dim_users.sql",
            line=42,
            col=1,
        ),
        LintFinding(
            check="nopositionalgroupbyororderby",
            severity="warning",
            message="Positional reference found.",
            model="dim_users",
            path="models/core/dim_users.sql",
            line=50,
        ),
    ]

    render_lint_report(
        findings,
        models_checked=5,
        executed_checks=["sqlmesh"],
        console=console,
        group_by="model",
        duration=0.38,
    )

    output = console.export_text()
    assert "TFF ARCHITECTURE AUDIT" in output
    assert "5 models" in output
    assert "1 error" in output
    assert "1 warning" in output
    assert "0.38s" in output
    assert "models/core/dim_users.sql" in output
    assert "42:1" in output
    assert "50:1" in output
    assert "banselectstar" in output
    assert "name" in output
    assert "position" in output
    assert "FAIL — 1 error block merge. Run `tff --fix` for auto-correctable rules." in output


def test_format_connascence_tag_helper() -> None:
    from tff.core.report import _format_connascence_tag

    assert _format_connascence_tag("Connascence of Name (CoN)") == "name"
    assert _format_connascence_tag("Connascence of Meaning (CoM)") == "meaning"
    assert _format_connascence_tag("Connascence of Algorithm (CoA)") == "algorithm"
    assert _format_connascence_tag("Connascence of Position (CoP)") == "position"
    assert _format_connascence_tag("Connascence of Value (CoV)") == "value"
    assert _format_connascence_tag("Connascence of Type (CoT)") == "type"
    assert _format_connascence_tag("Dynamic Coupling & DAG Structure") == "dynamic"
    assert _format_connascence_tag("Quality & Metadata (Non-Connascence)") == "metadata"
    assert _format_connascence_tag("Unknown Category") == "Unknown Category"


def test_is_fixable_finding_helper() -> None:
    from tff.core.report import LintFinding, _is_fixable_finding

    f1 = LintFinding(check="nopositionalgroupbyororderby", severity="error", message="pos")
    f2 = LintFinding(check="nomissingdescription", severity="warning", message="desc")
    f3 = LintFinding(check="sqlcomplexity", severity="error", message="nested subquery in final SELECT")
    f4 = LintFinding(check="sqlcomplexity", severity="error", message="too many CTEs")
    f5 = LintFinding(check="banselectstar", severity="error", message="select *")

    assert _is_fixable_finding(f1) is True
    assert _is_fixable_finding(f2) is True
    assert _is_fixable_finding(f3) is True
    assert _is_fixable_finding(f4) is False
    assert _is_fixable_finding(f5) is False


def test_render_lint_report_connascence_model_without_path_and_custom_rule() -> None:
    """Verify connascence rendering when model has no path and rule has no docs URL."""
    from rich.console import Console
    from tff.core.report import LintFinding, render_lint_report

    console = Console(record=True, width=120)
    findings = [
        LintFinding(
            check="custom_rule_without_url",
            severity="error",
            message="Custom violation without url.",
            model="dim_users",
            path=None,
        ),
    ]

    render_lint_report(
        findings,
        models_checked=1,
        console=console,
        group_by="connascence",
    )

    output = console.export_text()
    assert "dim_users" in output
    assert "custom_rule_without_url" in output


def test_render_lint_report_pass_and_warn_fail_level() -> None:
    """Verify footer text for zero findings (PASS) and fail_level='warning'."""
    from rich.console import Console
    from tff.core.report import LintFinding, render_lint_report

    # 1. Zero findings -> PASS
    console_pass = Console(record=True, width=120)
    passed = render_lint_report([], models_checked=5, console=console_pass)
    assert passed is True
    assert "PASS — all fitness functions satisfied." in console_pass.export_text()

    # 2. Only warning with fail_level='warning' -> FAIL
    console_warn_fail = Console(record=True, width=120)
    warning_finding = LintFinding(
        check="sqlcomplexity",
        severity="warning",
        message="High complexity",
        model="orders",
        path="models/orders.sql",
    )
    failed = render_lint_report(
        [warning_finding],
        models_checked=1,
        fail_level="warning",
        console=console_warn_fail,
    )
    assert failed is False
    assert "FAIL — 1 warning block merge." in console_warn_fail.export_text()










