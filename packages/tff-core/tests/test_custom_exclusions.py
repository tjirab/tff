import json
from pathlib import Path

from tff.core.model import ModelRepresentation
from tff.core.checks.custom_exclusions import CustomExclusionsChecker


def test_custom_exclusions_checker_skips_missing_models(tmp_path: Path) -> None:
    exclusions_file = tmp_path / "exclusions.json"
    exclusions_file.write_text(json.dumps({
        "exclusions": [
            {"source_layer": "core", "target_layer": "derived"}
        ]
    }), encoding="utf-8")

    model = ModelRepresentation(
        name="derived.model_a",
        path="models/derived/model_a.sql",
        dialect="bigquery",
        depends_on={"core.model_b"},
    )
    
    # Empty dictionary of models, so core.model_b is missing
    checker = CustomExclusionsChecker({}, exclusions_file)
    violations = checker.check_model(model)
    assert violations == []


def test_custom_exclusions_checker_detects_violations(tmp_path: Path) -> None:
    exclusions_file = tmp_path / "exclusions.json"
    exclusions_file.write_text(json.dumps({
        "exclusions": [
            {"source_layer": "core", "target_layer": "derived"}
        ]
    }), encoding="utf-8")

    model_a = ModelRepresentation(
        name="derived.model_a",
        path="models/derived/model_a.sql",
        dialect="bigquery",
        depends_on={"core.model_b"},
    )
    model_b = ModelRepresentation(
        name="core.model_b",
        path="models/core/model_b.sql",
        dialect="bigquery",
    )

    models = {
        "derived.model_a": model_a,
        "core.model_b": model_b,
    }

    checker = CustomExclusionsChecker(models, exclusions_file)
    violations = checker.check_model(model_a)
    assert len(violations) == 1
    assert "not allowed by custom exclusions" in violations[0]


def test_custom_exclusions_by_tags_and_meta(tmp_path: Path) -> None:
    from tff.core.config import FitnessFunctionsConfig, ChecksConfig, CustomExclusionsCheckConfig, CustomExclusionRule
    
    # Define models with non-standard paths, but with tags and meta
    model_a = ModelRepresentation(
        name="theme_a.model_a",
        path="functional_theme/theme_a/model_a.sql", # non-standard path!
        dialect="bigquery",
        depends_on={"theme_b.model_b"},
        tags=["pii"],
        meta={"team": "finance"},
    )
    model_b = ModelRepresentation(
        name="theme_b.model_b",
        path="functional_theme/theme_b/model_b.sql", # non-standard path!
        dialect="bigquery",
        tags=["public"],
        meta={"team": "marketing"},
    )
    
    models = {
        "theme_a.model_a": model_a,
        "theme_b.model_b": model_b,
    }
    
    # 1. Test fallback resolution of layer and domain
    from tff.core.utils.paths import resolve_layer_and_domain
    layer_order = ["sources", "derived", "core", "marts", "export"]
    
    layer, domain = resolve_layer_and_domain(model_a, layer_order)
    assert layer is None
    assert domain is None

    # Now let's specify layer/domain via tags and meta
    model_a.tags.append("core")
    model_a.meta["domain"] = "finance"
    
    model_b.meta["layer"] = "marts"
    model_b.tags.append("domain:marketing")
    
    layer_a, domain_a = resolve_layer_and_domain(model_a, layer_order)
    assert layer_a == "core"
    assert domain_a == "finance"
    
    layer_b, domain_b = resolve_layer_and_domain(model_b, layer_order)
    assert layer_b == "marts"
    assert domain_b == "marketing"

    # 2. Test CustomExclusionsConfig rule with tags & meta selectors
    from tff.core.context import set_ff_config

    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            custom_exclusions=CustomExclusionsCheckConfig(
                enabled=True,
                exclusions=[
                    # Rules that should NOT match (to cover the non-matching branches)
                    CustomExclusionRule(
                        source_layer="marts",  # source is actually core (does not match)
                        target_layer="derived",
                    ),
                    CustomExclusionRule(
                        source_layer="core",
                        source_domain="wrong_domain",  # source domain does not match
                        target_layer="derived",
                    ),
                    CustomExclusionRule(
                        source_tag="non_existent_tag",  # does not match source
                        target_tag="pii",
                    ),
                    CustomExclusionRule(
                        source_tags=["public", "another_non_existent"],  # does not match source
                        target_tag="pii",
                    ),
                    CustomExclusionRule(
                        source_meta={"team": "wrong_team"},  # does not match source
                        target_tag="pii",
                    ),
                    CustomExclusionRule(
                        source_tag="public",
                        target_layer="marts",  # target layer does not match
                    ),
                    CustomExclusionRule(
                        source_tag="public",
                        target_domain="wrong_domain",  # target domain does not match
                    ),
                    CustomExclusionRule(
                        source_tag="public",
                        target_tag="non_existent_tag",  # target tag does not match
                    ),
                    CustomExclusionRule(
                        source_tag="public",
                        target_tags=["pii", "non_existent"],  # target tags does not match
                    ),
                    CustomExclusionRule(
                        source_tag="public",
                        target_meta={"team": "wrong_team"},  # target meta does not match
                    ),
                    # Exclude a model with tag "pii" depending on tag "public" (MATCH)
                    CustomExclusionRule(
                        source_tag="public",
                        target_tag="pii",
                    ),
                    # Exclude a model with meta team=finance depending on team=marketing (MATCH)
                    CustomExclusionRule(
                        source_meta={"team": "marketing"},
                        target_meta={"team": "finance"},
                    )
                ]
            )
        )
    )
    
    exclusions_file = tmp_path / "exclusions.json"
    exclusions_file.write_text(json.dumps({"exclusions": []}), encoding="utf-8")
    
    checker = CustomExclusionsChecker(models, exclusions_file, config=config)
    
    violations = checker.check_model(model_a)
    assert len(violations) > 0

    # 3. Test resolve_layer_and_domain without layer_order parameter (uses context config)
    set_ff_config(config)
    layer_def, domain_def = resolve_layer_and_domain(model_a)
    assert layer_def == "core"
    assert domain_def == "finance"


def test_custom_exclusions_additional_coverage(tmp_path: Path) -> None:
    from tff.core.config import FitnessFunctionsConfig, ChecksConfig, CustomExclusionsCheckConfig, CustomExclusionRule, AllowedExceptionRule
    
    # 1. Test config-based allowed exceptions
    model_a = ModelRepresentation(
        name="derived.model_a",
        path="models/derived/model_a.sql",
        dialect="bigquery",
        depends_on={"core.model_b"},
    )
    model_b = ModelRepresentation(
        name="core.model_b",
        path="models/core/model_b.sql",
        dialect="bigquery",
    )
    
    models = {
        "derived.model_a": model_a,
        "core.model_b": model_b,
    }
    
    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            custom_exclusions=CustomExclusionsCheckConfig(
                enabled=True,
                exclusions=[
                    CustomExclusionRule(
                        source_layer="core",
                        target_layer="derived",
                    )
                ],
                allowed_exceptions=[
                    AllowedExceptionRule(
                        model="derived.model_a",
                        dependency="core.model_b",
                    )
                ]
            )
        )
    )
    
    exclusions_file = tmp_path / "exclusions.json"
    exclusions_file.write_text(json.dumps({"exclusions": []}), encoding="utf-8")
    
    checker = CustomExclusionsChecker(models, exclusions_file, config=config)
    
    # Should not have violations due to allowed exceptions
    violations = checker.check_model(model_a)
    assert violations == []

    # 2. Test _is_excluded_dependency direct call without source_model/target_model
    model_c = ModelRepresentation(
        name="core.model_c",
        path="models/core/model_c.sql",
        dialect="bigquery",
    )
    models["core.model_c"] = model_c
    is_ex_c = checker._is_excluded_dependency(
        source_layer="core",
        source_domain="",
        target_layer="derived",
        target_domain="",
        model_name="derived.model_a",
        dependency_name="core.model_c",
    )
    assert is_ex_c is True

    # 3. Test when source_model / target_model are missing from self.models to trigger the else block of tags/meta matching
    config_meta = FitnessFunctionsConfig(
        checks=ChecksConfig(
            custom_exclusions=CustomExclusionsCheckConfig(
                enabled=True,
                exclusions=[
                    CustomExclusionRule(
                        source_tag="pii",
                        target_tag="public",
                    )
                ]
            )
        )
    )
    checker_empty = CustomExclusionsChecker({}, exclusions_file, config=config_meta)
    is_ex_empty = checker_empty._is_excluded_dependency(
        source_layer="core",
        source_domain="",
        target_layer="derived",
        target_domain="",
        model_name="derived.model_a",
        dependency_name="core.model_b",
    )
    assert is_ex_empty is False


def test_layer_integrity_missing_dependency() -> None:
    from tff.core.checks.layer_integrity import collect_layer_integrity_findings
    from tff.core.config import FitnessFunctionsConfig
    
    config = FitnessFunctionsConfig()
    
    model = ModelRepresentation(
        name="derived.model_a",
        path="models/derived/model_a.sql",
        dialect="bigquery",
        depends_on={"core.non_existent"}, # depends on non-existent model!
    )
    
    models = {
        "derived.model_a": model,
    }
    
    findings = collect_layer_integrity_findings(models, config)
    # Should not crash, and should just skip the non-existent dependency
    assert findings == []
