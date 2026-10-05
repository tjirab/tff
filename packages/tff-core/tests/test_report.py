from __future__ import annotations

from typing import Any
import pytest
from conftest import _make_finding
from tff.core.report import (
    _format_check_cell,
    _append_check_tag,
    _format_connascence_tag,
    _format_file_reference,
    _is_fixable_finding,
    _summary_check_names,
    group_findings_by_model,
    normalize_model_name,
    render_lint_report,
)


@pytest.mark.parametrize(
    ("executed", "by_check", "expected"),
    [
        (["layer_integrity"], {}, ["layer_integrity"]),
        (["sqlmesh"], {}, ["classificationmacros", "sqlcomplexity"]),
        (["sqlmesh"], {"nomissinggrain": {"error": 2, "warning": 0}}, ["nomissinggrain"]),
        (
            [
                "sqlmesh",
                "layer_integrity",
                "custom_exclusions",
                "schema_contracts",
                "dependency_graph",
            ],
            {},
            [
                "layer_integrity",
                "custom_exclusions",
                "schema_contracts",
                "dependency_graph",
                "classificationmacros",
                "sqlcomplexity",
            ],
        ),
    ],
)
def test_summary_check_names(
    executed: list[str], by_check: dict[str, Any], expected: list[str]
) -> None:
    assert set(_summary_check_names(executed, by_check)) == set(expected)


@pytest.mark.parametrize("group_by", ["connascence", "model"])
def test_render_lint_report_groups_by_mode(group_by: str) -> None:
    from rich.console import Console

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
        _make_finding(
            check="classificationmacros",
            severity="warning",
            message="Inline CASE defines product_type",
            model="core.orders",
            path="models/core/orders.sql",
        ),
        _make_finding(
            check="layer_integrity",
            severity="error",
            message="depends on downstream model",
            model="core.orders",
            path="models/core/orders.sql",
        ),
        _make_finding(
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
        group_by=group_by,
    )

    assert success is False
    output = console.export_text()
    assert "TFF ARCHITECTURE AUDIT" in output
    assert "models/marts/users.sql" in output
    assert "models/core/orders.sql" in output
    if group_by == "connascence":
        assert "banselectstar" in output
        assert "classificationmacros" in output
        assert "layer_integrity" in output
        assert "schema_contracts" in output
    else:
        assert "Connascence of Name (CoN)" not in output


def test_render_lint_report_groups_by_connascence_cop() -> None:
    from rich.console import Console

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
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


@pytest.mark.parametrize("group_by", ["connascence", "model"])
def test_render_lint_report_warnings_and_multiline(group_by: str) -> None:
    from rich.console import Console

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
            check="banselectstar",
            severity="warning",
            message="SELECT *\nis prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
        _make_finding(
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
        group_by=group_by,
    )
    assert success is True

    output = console.export_text()
    assert "SELECT *" in output
    assert "is prohibited." in output
    if group_by == "connascence":
        assert "WARN —" in output
        assert "models/marts/users.sql" in output
    else:
        assert "TFF ARCHITECTURE AUDIT" in output


@pytest.mark.parametrize(
    "check,expected_plain,has_link,expected_style",
    [
        ("banselectstar", "No SELECT *", True, None),
        ("custom_unknown_check", "custom_unknown_check", False, "bold"),
    ],
)
def test_format_check_cell(
    check: str, expected_plain: str, has_link: bool, expected_style: str | None
) -> None:
    from tff.core.registry import registry

    cell = _format_check_cell(check)
    assert cell.plain == expected_plain
    if has_link:
        docs_url = registry.get_docs_url(check)
        assert docs_url is not None
        assert f"link {docs_url}" in str(cell.style)
    if expected_style:
        assert cell.style == expected_style


@pytest.mark.parametrize(
    "check,expected_plain,has_link,expected_style",
    [
        ("banselectstar", "Issue message (banselectstar)", True, None),
        ("custom_unknown_check", "Issue message (custom_unknown_check)", False, "dim"),
    ],
)
def test_append_check_tag(
    check: str, expected_plain: str, has_link: bool, expected_style: str | None
) -> None:
    from rich.text import Text
    from tff.core.registry import registry

    text = Text("Issue message ")
    _append_check_tag(text, check)
    assert text.plain == expected_plain
    span = text.spans[0]
    if has_link:
        docs_url = registry.get_docs_url(check)
        assert docs_url is not None
        assert f"link {docs_url}" in str(span.style)
    if expected_style:
        assert span.style == expected_style


def test_render_lint_report_hyperlinks_in_terminal_output() -> None:
    from rich.console import Console
    from tff.core.registry import registry

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="marts.users",
            path="models/marts/users.sql",
        ),
        _make_finding(
            check="layer_integrity",
            severity="error",
            message="Repo level architecture failure.",
            model=None,
            path=None,
        ),
        _make_finding(
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
    html_output = console.export_html(clear=False)
    assert f'href="{docs_url}"' in html_output
    text_output = console.export_text()
    assert "https://tff.readthedocs.io" not in text_output
    assert "banselectstar" in text_output
    assert "layer_integrity" in text_output
    assert "unknown_rule" in text_output


def test_render_lint_report_connascence_grouping_hyperlinks() -> None:
    from rich.console import Console
    from tff.core.registry import registry

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
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


@pytest.mark.parametrize(
    "raw_name,expected_norm",
    [
        ("model.my_project.dim_users", "dim_users"),
        ("source.my_project.raw_users", "raw_users"),
        ("seed.my_project.country_codes", "country_codes"),
        ("snapshot.my_project.orders_snapshot", "orders_snapshot"),
        ('"model"."my_project"."dim_users"', "dim_users"),
        ("sqlmesh_example.dim_users", "sqlmesh_example.dim_users"),
        ("catalog.sqlmesh_example.dim_users", "sqlmesh_example.dim_users"),
        ("dim_users", "dim_users"),
    ],
)
def test_normalize_model_name(raw_name: str, expected_norm: str) -> None:
    assert normalize_model_name(raw_name) == expected_norm


def test_group_findings_by_model_unifies_model_headings_across_checks() -> None:
    """Findings across different checks with matching model identifiers unify into one group."""
    findings = [
        _make_finding(
            check="dependency_graph",
            severity="error",
            message="fan_out=5 (fail>2) — high blast-radius hub model",
            model="dbt_example.dim_users",
            path="models/core/dim_users.sql",
        ),
        _make_finding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="dim_users",
            path="models/core/dim_users.sql",
        ),
        _make_finding(
            check="materialization_depth",
            severity="warning",
            message="View nesting depth is 3",
            model="model.dbt_example.dim_users",
            path="models/core/dim_users.sql",
        ),
    ]

    groups, repo = group_findings_by_model(findings)
    assert len(groups) == 1
    assert groups[0]["name"] == "dim_users"
    assert groups[0]["path"] == "models/core/dim_users.sql"
    assert len(groups[0]["findings"]) == 3
    assert len(repo) == 0


def test_group_findings_by_model_edge_cases() -> None:
    """Group findings properly handles path-only, model-only, and stem matching."""
    findings = [
        _make_finding(
            check="banselectstar",
            model=None,
            path="models/staging/stg_only_path.sql",
        ),
        _make_finding(
            check="sqlcomplexity",
            severity="warning",
            model="orders",
            path=None,
        ),
        _make_finding(
            check="banselectstar",
            model="orders",
            path="models/marts/orders.sql",
        ),
        _make_finding(
            check="banselectstar",
            model="customers",
            path="models/marts/customers.sql",
        ),
        _make_finding(
            check="sqlcomplexity",
            severity="warning",
            model="customers",
            path=None,
        ),
        _make_finding(
            check="nomissingowner",
            model="reports",
            path=None,
        ),
        _make_finding(
            check="banselectstar",
            model=None,
            path="models/marts/reports.sql",
        ),
    ]

    groups, repo = group_findings_by_model(findings)
    assert len(repo) == 0
    group_names = {g["name"] for g in groups}
    assert group_names == {"stg_only_path", "orders", "customers", "reports"}
    group_paths = {g["path"] for g in groups}
    assert "models/marts/orders.sql" in group_paths
    assert "models/marts/customers.sql" in group_paths
    assert "models/marts/reports.sql" in group_paths


@pytest.mark.parametrize("group_by", ["model", "connascence"])
def test_render_lint_report_multiline_finding_formatting(group_by: str) -> None:
    """Multi-line findings format cleanly with rule tag on line 1 and sub-bullets indented below."""
    from rich.console import Console

    multiline_msg = (
        "another_user_model.sql does not match dim_users.sql:\n"
        "  - missing columns: api_request, bad_id\n"
        "  + extra columns: email_flag"
    )
    findings = [
        _make_finding(
            check="schema_contracts",
            severity="error",
            message=multiline_msg,
            model=None,
            path=None,
        ),
        _make_finding(
            check="schema_contracts",
            severity="error",
            message=multiline_msg,
            model="user_model",
            path="models/marts/user_model.sql",
        ),
    ]

    console = Console(record=True, width=120)
    render_lint_report(
        findings,
        models_checked=2,
        executed_checks=["schema_contracts"],
        console=console,
        group_by=group_by,
    )
    out = console.export_text()
    assert "another_user_model.sql does not match dim_users.sql:" in out
    assert "schema_contracts" in out
    assert "  - missing columns: api_request, bad_id" in out
    assert "  + extra columns: email_flag" in out


def test_render_lint_report_with_duration() -> None:
    from rich.console import Console

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


@pytest.mark.parametrize(
    "kwargs,expected_plain",
    [
        ({"path": "models/core/dim_users.sql"}, "models/core/dim_users.sql"),
        ({"path": "models/core/dim_users.sql", "line": 42}, "models/core/dim_users.sql:42"),
    ],
)
def test_format_file_reference(kwargs: dict[str, Any], expected_plain: str) -> None:
    ref = _format_file_reference(**kwargs)
    assert ref.plain == expected_plain
    assert "link file://" in str(ref.style)


@pytest.mark.parametrize(
    "group_by,path,line,expected_substr",
    [
        ("model", "models/core/dim_users.sql", 42, "42:1"),
        ("connascence", "models/marts/users.sql", 10, "models/marts/users.sql:10"),
    ],
)
def test_render_lint_report_shows_line_coordinates(
    group_by: str, path: str, line: int, expected_substr: str
) -> None:
    from rich.console import Console

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="dim_users",
            path=path,
            line=line,
        ),
    ]

    render_lint_report(
        findings,
        models_checked=1,
        executed_checks=["sqlmesh"],
        console=console,
        group_by=group_by,
    )

    output = console.export_text(clear=False)
    assert expected_substr in output
    assert "file://" in console.export_html(clear=False)


def test_render_lint_report_model_header_has_clickable_file_link() -> None:
    """Model header path is wrapped in an OSC 8 file:// hyperlink."""
    from rich.console import Console

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
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
    groups, repo = group_findings_by_model(findings)
    assert len(groups) == 1
    assert groups[0]["name"] == expected_name
    assert groups[0]["path"] == expected_path
    assert len(groups[0]["findings"]) == len(findings)
    assert len(repo) == 0


def test_group_findings_by_model_bridge_merges_disjoint_and_prevents_stale_lookup() -> None:
    """Findings that bridge disjoint groups merge them and re-point path_to_key without KeyError."""
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

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
            check="banselectstar",
            severity="error",
            message="SELECT * is prohibited.",
            model="dim_users",
            path="models/core/dim_users.sql",
            line=42,
            col=1,
        ),
        _make_finding(
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


@pytest.mark.parametrize(
    "category,expected_tag",
    [
        ("Connascence of Name (CoN)", "name"),
        ("Connascence of Meaning (CoM)", "meaning"),
        ("Connascence of Algorithm (CoA)", "algorithm"),
        ("Connascence of Position (CoP)", "position"),
        ("Connascence of Value (CoV)", "value"),
        ("Connascence of Type (CoT)", "type"),
        ("Dynamic Coupling & DAG Structure", "dynamic"),
        ("Quality & Metadata (Non-Connascence)", "metadata"),
        ("Unknown Category", "Unknown Category"),
    ],
)
def test_format_connascence_tag_helper(category: str, expected_tag: str) -> None:
    assert _format_connascence_tag(category) == expected_tag


@pytest.mark.parametrize(
    "check,message,expected_fixable",
    [
        ("nopositionalgroupbyororderby", "pos", True),
        ("nomissingdescription", "desc", True),
        ("martmodelnamingconvention", "mart", True),
        ("mart_naming", "mart", True),
        ("filenameequalsmodelname", "name", True),
        ("filename_equals_modelname", "name", True),
        ("sqlcomplexity", "nested subquery in final SELECT", True),
        ("sqlcomplexity", "too many CTEs", False),
        ("banselectstar", "select *", True),
        ("ban_select_star", "select *", True),
        ("jointypeparity", "type mismatch", False),
    ],
)
def test_is_fixable_finding_helper(check: str, message: str, expected_fixable: bool) -> None:
    f = _make_finding(check=check, message=message)
    assert _is_fixable_finding(f) is expected_fixable


def test_render_lint_report_connascence_model_without_path_and_custom_rule() -> None:
    """Verify connascence rendering when model has no path and rule has no docs URL."""
    from rich.console import Console

    console = Console(record=True, width=120)
    findings = [
        _make_finding(
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


@pytest.mark.parametrize(
    ("findings", "models_checked", "fail_level", "expected_success", "expected_text"),
    [
        ([], 5, "error", True, "PASS — all fitness functions satisfied."),
        (
            [_make_finding(check="sqlcomplexity", severity="warning", message="High complexity", model="orders")],
            1,
            "warning",
            False,
            "FAIL — 1 warning block merge.",
        ),
    ],
)
def test_render_lint_report_status_footers(
    findings: list[Any],
    models_checked: int,
    fail_level: str,
    expected_success: bool,
    expected_text: str,
) -> None:
    from rich.console import Console

    console = Console(record=True, width=120)
    passed = render_lint_report(
        findings,
        models_checked=models_checked,
        fail_level=fail_level,
        console=console,
    )
    assert passed is expected_success
    assert expected_text in console.export_text()
