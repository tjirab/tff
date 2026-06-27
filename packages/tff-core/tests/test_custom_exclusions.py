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
        depends_on={"core.model_b"},
    )
    model_b = ModelRepresentation(
        name="core.model_b",
        path="models/core/model_b.sql",
    )

    models = {
        "derived.model_a": model_a,
        "core.model_b": model_b,
    }

    checker = CustomExclusionsChecker(models, exclusions_file)
    violations = checker.check_model(model_a)
    assert len(violations) == 1
    assert "not allowed by custom exclusions" in violations[0]
