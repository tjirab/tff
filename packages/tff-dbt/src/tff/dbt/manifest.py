from __future__ import annotations

import json
from pathlib import Path

from tff.core.model import ModelRepresentation


def load_dbt_models(
    project_root: Path,
    target_dir: str = "target",
    dialect: str = "bigquery",
) -> dict[str, ModelRepresentation]:
    manifest_path = project_root / target_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"dbt manifest not found at {manifest_path}. Please run 'dbt compile' first."
        )

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # 1. Collect tests by model unique ID
    model_tests: dict[str, list[tuple[str, dict]]] = {}
    for unique_id, node in manifest.get("nodes", {}).items():
        if node.get("resource_type") == "test":
            test_metadata = node.get("test_metadata", {})
            test_name = test_metadata.get("name")
            if not test_name:
                continue

            depends_on_nodes = node.get("depends_on", {}).get("nodes", [])
            for dep in depends_on_nodes:
                if dep.startswith("model.") or dep.startswith("seed."):
                    if dep not in model_tests:
                        model_tests[dep] = []
                    model_tests[dep].append((test_name, test_metadata.get("kwargs", {})))

    # 2. Map nodes of type 'model' and 'seed' to ModelRepresentation
    mapped_models: dict[str, ModelRepresentation] = {}
    for unique_id, node in manifest.get("nodes", {}).items():
        resource_type = node.get("resource_type")
        if resource_type not in ("model", "seed"):
            continue

        name = node.get("name", "")

        # Map column types
        columns_to_types = {}
        for col_name, col_meta in node.get("columns", {}).items():
            col_type = col_meta.get("data_type") or "unknown"
            columns_to_types[col_name.lower()] = col_type.lower()

        # Metadata parsing
        meta = node.get("meta", {})
        owner = meta.get("owner") or node.get("config", {}).get("meta", {}).get("owner")

        grains_raw = meta.get("grain") or meta.get("grains") or []
        if isinstance(grains_raw, str):
            grains = [grains_raw]
        elif isinstance(grains_raw, list):
            grains = [str(g) for g in grains_raw]
        else:
            grains = []

        # Dependencies
        depends_on = set(node.get("depends_on", {}).get("nodes", []))
        depends_on = {
            dep
            for dep in depends_on
            if dep.startswith("model.") or dep.startswith("seed.") or dep.startswith("source.")
        }

        # Ephemeral models behave like symbolic models
        is_symbolic = node.get("config", {}).get("materialized") == "ephemeral"

        rel_path = node.get("original_file_path", "")
        abs_path = str(project_root / rel_path)

        audits = model_tests.get(unique_id, [])

        mapped_models[unique_id] = ModelRepresentation(
            name=name,
            path=abs_path,
            dialect=dialect,
            is_symbolic=is_symbolic,
            is_external=False,
            columns_to_types=columns_to_types,
            depends_on=depends_on,
            description=node.get("description"),
            owner=owner,
            grains=grains,
            audits=audits,
        )

    # 3. Map sources to ModelRepresentation so graph checks resolve them
    for source_id, source in manifest.get("sources", {}).items():
        name = source.get("name", "")
        rel_path = source.get("original_file_path", "")
        abs_path = str(project_root / rel_path)

        mapped_models[source_id] = ModelRepresentation(
            name=name,
            path=abs_path,
            dialect=dialect,
            is_symbolic=True,
            is_external=True,
            columns_to_types={},
            depends_on=set(),
            description=source.get("description"),
            owner=source.get("meta", {}).get("owner"),
            grains=[],
            audits=[],
        )

    return mapped_models
