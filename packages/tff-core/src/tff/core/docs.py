"""Dashboard compiler and HTML template generator for Transformation Fitness Functions."""

from __future__ import annotations

import importlib.resources
import json
from datetime import date
from pathlib import Path
from typing import Any, Sequence

from tff.core.config import load_fitness_config
from tff.core.health import calculate_health_scores
from tff.core.logs import collect_stats, get_health_json_data, save_log
from tff.core.registry import registry
from tff.core.utils.paths import model_path_relative


def _load_dashboard_template() -> str:
    """Load the static interactive HTML dashboard template from package resources."""
    return (
        importlib.resources.files("tff.core.templates")
        .joinpath("dashboard.html")
        .read_text(encoding="utf-8")
    )


HTML_TEMPLATE: str = _load_dashboard_template()
_HTML_TEMPLATE: str = HTML_TEMPLATE


def generate_docs_dashboard(
    project_root: Path | Sequence[Path | str] | str,
    output_path: Path | None = None,
    provider: str = "auto",
    dialect: str | None = None,
    config_path: str = "fitness_functions.yaml",
    manifest_path: str | Path | None = None,
    no_log: bool = False,
    workers: int | None = None,
    chunk_size: int | None = None,
) -> Path:
    """Run checks, compile, and output a standalone interactive HTML dashboard."""
    from tff.core.adapter import normalize_project_roots

    roots = normalize_project_roots(project_root)
    primary_root = roots[0]

    # 1. Load config
    config = load_fitness_config(roots, config_path=config_path)
    if workers is not None:
        config.workers = workers
    if chunk_size is not None:
        config.chunk_size = chunk_size

    # 2. Get adapter
    if provider == "auto":
        from tff.core.adapter import detect_provider

        provider = detect_provider(roots)

    from tff.core.cli import _get_adapter

    adapter = _get_adapter(provider)

    # 3. Load models mapping
    models = adapter.load_models(
        project_root=roots,
        dialect=dialect,
        manifest_path=manifest_path,
    )

    # 4. Run all checks reusing preloaded models
    run_kwargs: dict[str, Any] = {
        "project_root": roots,
        "config": config,
        "dialect": dialect,
        "manifest_path": manifest_path,
        "models": models,
    }
    if chunk_size is not None:
        import inspect

        sig = inspect.signature(adapter.run_checks)
        if "chunk_size" in sig.parameters or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
        ):
            run_kwargs["chunk_size"] = chunk_size

    findings, models_checked, executed_checks = adapter.run_checks(**run_kwargs)

    # 5. Calculate scores and save health log
    scores = calculate_health_scores(findings, models_checked, config, provider)
    json_data = get_health_json_data(scores, models_checked)
    save_log(primary_root, "health", json_data, no_log=no_log)

    # 6. Collect history (60 days)
    history = collect_stats(roots, days=60)
    if not history:
        history = [
            {
                "date": date.today().isoformat(),
                "health_score": scores["overall_score"],
                "errors_count": len([f for f in findings if f.severity == "error"]),
                "warnings_count": len([f for f in findings if f.severity == "warning"]),
            }
        ]

    # 7. Prep data for the HTML template
    rel_to_model_id = {
        model_path_relative(m): m_id for m_id, m in models.items() if m.path
    }
    name_to_model_id = {m.name: m_id for m_id, m in models.items()}

    model_findings_serialized: dict[str, list[dict[str, Any]]] = {}
    project_findings: list[dict[str, Any]] = []

    for f in findings:
        serialized_f = {
            "check": f.check,
            "severity": f.severity,
            "message": f.message,
            "path": f.path,
        }

        # Try finding by path first, fallback to name
        m_id = None
        if f.path:
            m_id = rel_to_model_id.get(f.path)
        if not m_id and f.model:
            m_id = name_to_model_id.get(f.model)

        if m_id:
            if m_id not in model_findings_serialized:
                model_findings_serialized[m_id] = []
            model_findings_serialized[m_id].append(serialized_f)
        else:
            project_findings.append(serialized_f)

    # Serialize models
    serialized_models = {}
    for m_id, m in models.items():
        m_findings = model_findings_serialized.get(m_id, [])
        status = "pass"
        if any(f["severity"] == "error" for f in m_findings):
            status = "error"
        elif any(f["severity"] == "warning" for f in m_findings):
            status = "warning"

        serialized_models[m_id] = {
            "id": m_id,
            "name": m.name,
            "path": model_path_relative(m),
            "materialized": m.materialized,
            "owner": m.owner,
            "description": m.description,
            "grains": m.grains,
            "depends_on": list(m.depends_on),
            "is_external": m.is_external,
            "is_symbolic": m.is_symbolic,
            "findings": m_findings,
            "status": status,
        }

    # 8. Render HTML
    data_to_embed = {
        "overall_score": scores["overall_score"],
        "category_scores": scores["category_scores"],
        "models": serialized_models,
        "project_findings": project_findings,
        "history": history,
        "provider": provider,
        "docs_urls": registry.get_docs_urls(),
        "generated_at": json_data["timestamp"],
    }

    embedded_json = json.dumps(data_to_embed, indent=2)
    html_content = HTML_TEMPLATE.replace(
        "<!-- INSERT_TFF_DATA_HERE -->", f"const TFF_DATA = {embedded_json};"
    )

    if output_path is None:
        output_path = primary_root / "tff_report.html"
    else:
        output_path = Path(output_path)
        if not output_path.is_absolute():
            output_path = primary_root / output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path
