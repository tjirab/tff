"""Tests for systematic documentation URL resolution across registry, formatters, action, and docs."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tff.core.action import _format_check_cell, generate_pr_comment_markdown
from tff.core.docs import generate_docs_dashboard
from tff.core.formatters import generate_sarif_report
from tff.core.model import ModelRepresentation
from tff.core.registry import CheckRegistry, registry
from tff.core.report import LintFinding
from tff.core.rules.base import Rule, RuleViolation



def test_registry_docs_urls_presence() -> None:
    """Ensure all core architectural checks and rules have valid ReadTheDocs documentation URLs."""
    from tff.core.registry import create_default_registry

    reg = create_default_registry()
    all_checks = reg.all_checks()
    assert len(all_checks) > 0

    base_url = "https://tff.readthedocs.io/rules_and_checks/"
    for check_def in all_checks:
        assert check_def.docs_url is not None, f"Check {check_def.id} is missing docs_url"
        assert check_def.docs_url.startswith(base_url), (
            f"Check {check_def.id} docs_url '{check_def.docs_url}' does not start with {base_url}"
        )



def test_registry_get_docs_url_resolution() -> None:
    """Test get_docs_url resolves canonical IDs, finding IDs, and aliases."""
    expected_cov = (
        "https://tff.readthedocs.io/rules_and_checks/#connascence-of-value-connascence_of_value"
    )
    assert registry.get_docs_url("connascence_of_value") == expected_cov

    # Check CoN and its alias
    expected_ban = "https://tff.readthedocs.io/rules_and_checks/#ban-select-ban_select_star"
    assert registry.get_docs_url("ban_select_star") == expected_ban
    assert registry.get_docs_url("banselectstar") == expected_ban

    # Check case and separator normalization
    assert registry.get_docs_url("BAN_SELECT_STAR") == expected_ban
    assert registry.get_docs_url("ban-select-star") == expected_ban

    # Check unknown check returns None
    assert registry.get_docs_url("non_existent_check") is None


def test_registry_get_docs_urls_dict() -> None:
    """Test get_docs_urls returns complete dictionary mapping."""
    urls = registry.get_docs_urls()
    assert isinstance(urls, dict)
    assert "connascence_of_value" in urls
    assert "layer_integrity" in urls
    assert "join_type_parity" in urls
    assert "duplicate_ctes" in urls
    assert "sqlcomplexity" in urls


def test_custom_rule_docs_url_registration() -> None:
    """Test custom rule registration with docs_url attribute and parameter."""
    reg = CheckRegistry()

    class CustomRuleWithAttr(Rule):
        name = "custom_attr_rule"
        docs_url = "https://example.com/custom_rule_docs"

        def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
            return None

    check_def1 = reg.register_rule(CustomRuleWithAttr)
    assert check_def1.docs_url == "https://example.com/custom_rule_docs"
    assert reg.get_docs_url("custom_attr_rule") == "https://example.com/custom_rule_docs"
    assert CustomRuleWithAttr().check_model(MagicMock()) is None

    class CustomPlainRule(Rule):
        name = "custom_plain_rule"

        def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
            return None

    check_def2 = reg.register_rule(
        CustomPlainRule, docs_url="https://example.com/explicit_docs"
    )
    assert check_def2.docs_url == "https://example.com/explicit_docs"
    assert reg.get_docs_url("custom_plain_rule") == "https://example.com/explicit_docs"
    assert CustomPlainRule().check_model(MagicMock()) is None


def test_action_format_check_cell() -> None:
    """Test _format_check_cell generates hyperlinks for recognized checks and backticks for others."""
    # Known check
    cell_cov = _format_check_cell("connascence_of_value")
    assert cell_cov == (
        "[`connascence_of_value`]"
        "(https://tff.readthedocs.io/rules_and_checks/#connascence-of-value-connascence_of_value)"
    )

    # Empty check
    assert _format_check_cell("") == "`unknown`"

    # Unknown check
    assert _format_check_cell("unregistered_custom_check") == "`unregistered_custom_check`"


def test_action_pr_comment_includes_check_links() -> None:
    """Test generate_pr_comment_markdown produces hyperlinked Check column rows."""
    current_data = {
        "overall_score": 85.0,
        "findings": [
            {
                "check": "connascence_of_value",
                "severity": "warning",
                "message": "Literal 'active' is duplicated",
                "model": "model_a",
                "path": "models/marts/model_a.sql",
            },
            {
                "check": "custom_unregistered_rule",
                "severity": "error",
                "message": "Custom rule failed",
                "model": "model_b",
                "path": "models/marts/model_b.sql",
            },
        ],
        "errors_count": 1,
        "warnings_count": 1,
        "category_scores": {},
    }
    base_data = {
        "overall_score": 90.0,
        "findings": [],
        "errors_count": 0,
        "warnings_count": 0,
    }

    comment = generate_pr_comment_markdown(
        current_data, base_data=base_data, fail_under=80.0, fail_level="error"
    )

    # Hyperlinked known check in both new violations and main detail table
    expected_cov_link = (
        "[`connascence_of_value`]"
        "(https://tff.readthedocs.io/rules_and_checks/#connascence-of-value-connascence_of_value)"
    )
    assert expected_cov_link in comment

    # Non-hyperlinked unknown check
    assert "`custom_unregistered_rule`" in comment
    assert "[`custom_unregistered_rule`]" not in comment


def test_sarif_help_uri_mapping() -> None:
    """Test generate_sarif_report populates helpUri with check docs_url."""
    findings = [
        LintFinding(
            check="connascence_of_value",
            severity="warning",
            message="CoV detected",
            model="stg_orders",
            path="models/stg_orders.sql",
        ),
        LintFinding(
            check="unknown_external_check",
            severity="error",
            message="Unknown check error",
            model="stg_users",
            path="models/stg_users.sql",
        ),
    ]

    report = generate_sarif_report(findings)
    rules = report["runs"][0]["tool"]["driver"]["rules"]
    rules_by_id = {r["id"]: r for r in rules}

    # Known check should have exact section anchor
    assert "connascence_of_value" in rules_by_id
    assert rules_by_id["connascence_of_value"]["helpUri"] == (
        "https://tff.readthedocs.io/rules_and_checks/#connascence-of-value-connascence_of_value"
    )

    # Unknown check should fall back to base docs
    assert "unknown_external_check" in rules_by_id
    assert rules_by_id["unknown_external_check"]["helpUri"] == (
        "https://tff.readthedocs.io/rules_and_checks/"
    )


@patch("tff.core.docs.save_log")
@patch("tff.core.cli._get_adapter")
def test_docs_dashboard_embeds_docs_urls(
    mock_get_adapter: MagicMock, mock_save_log: MagicMock, tmp_path: Path
) -> None:
    """Test that generate_docs_dashboard embeds docs_urls dictionary in HTML output."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    dbt_proj = project_dir / "dbt_project.yml"
    dbt_proj.write_text("name: test_project\nversion: '1.0.0'\n", encoding="utf-8")

    mock_adapter = MagicMock()
    mock_adapter.load_models.return_value = {}
    mock_adapter.run_checks.return_value = ([], 0, ["rules"])
    mock_get_adapter.return_value = mock_adapter

    out_file = generate_docs_dashboard(project_dir, no_log=True)
    assert out_file.exists()

    html = out_file.read_text(encoding="utf-8")
    assert "docs_urls" in html
    assert "connascence_of_value" in html
    assert (
        "https://tff.readthedocs.io/rules_and_checks/#connascence-of-value-connascence_of_value"
        in html
    )

