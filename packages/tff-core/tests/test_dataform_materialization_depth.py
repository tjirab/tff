import json
from pathlib import Path

from tff.core.config import ChecksConfig, FitnessFunctionsConfig, MaterializationDepthCheckConfig
from tff.core.checks.materialization_depth import collect_materialization_depth_findings
from tff.dataform.manifest import load_dataform_models
from tff.dataform.runner import run_all_checks


def test_dataform_materialization_depth(tmp_path: Path):
    manifest_data = {
        "tables": [
            {
                "target": {"schema": "s", "name": "v1"},
                "type": "view",
                "fileName": "definitions/staging/v1.sqlx",
                "dependencyTargets": [],
            },
            {
                "target": {"schema": "s", "name": "v2"},
                "type": "view",
                "fileName": "definitions/staging/v2.sqlx",
                "dependencyTargets": [{"schema": "s", "name": "v1"}],
            },
            {
                "target": {"schema": "s", "name": "v3"},
                "type": "view",
                "fileName": "definitions/staging/v3.sqlx",
                "dependencyTargets": [{"schema": "s", "name": "v2"}],
            },
            {
                "target": {"schema": "s", "name": "v4"},
                "type": "view",
                "fileName": "definitions/staging/v4.sqlx",
                "dependencyTargets": [{"schema": "s", "name": "v3"}],
            },
        ]
    }
    manifest_file = tmp_path / "compilation_result.json"
    manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

    models = load_dataform_models(tmp_path)
    config = FitnessFunctionsConfig(
        checks=ChecksConfig(
            materialization_depth=MaterializationDepthCheckConfig(
                enabled=True, max_depth_warn=2, max_depth_fail=3
            )
        )
    )

    findings = collect_materialization_depth_findings(models, config)
    assert len(findings) >= 1

    findings, checked, selected = run_all_checks(
        project_root=tmp_path, config=config, checks=["materialization_depth"]
    )
    assert "materialization_depth" in selected
    warns = [f for f in findings if f.severity == "warning"]
    errors = [f for f in findings if f.severity == "error"]
    assert len(warns) == 1
    assert len(errors) == 1
