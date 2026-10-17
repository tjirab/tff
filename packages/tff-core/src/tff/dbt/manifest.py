from __future__ import annotations

from collections import defaultdict
import json
import logging
from pathlib import Path
import shutil
import subprocess
from typing import TYPE_CHECKING, Any, Sequence

from tff.core.adapter import normalize_project_roots
from tff.core.model import ModelRepresentation
from tff.core.parallel import precompute_model_asts

if TYPE_CHECKING:
    from tff.core.config import FitnessFunctionsConfig

logger = logging.getLogger(__name__)


def _run_dbt_parse(project_root: Path) -> bool:
    """Attempt to generate manifest.json on-the-fly via dbt parse."""
    dbt_bin = shutil.which("dbt")
    cmd = [dbt_bin, "parse"] if dbt_bin else ["dbt", "parse"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode == 0:
            return True
        logger.debug(
            "dbt parse failed for %s (exit code %d): %s",
            project_root,
            proc.returncode,
            proc.stderr,
        )
        return False
    except Exception as exc:
        logger.debug("Failed to invoke dbt parse in %s: %s", project_root, exc)
        return False


def _load_single_manifest(
    root: Path,
    target_dir: str = "target",
    manifest_path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and parse manifest.json for a single project root with dbt parse fallback."""
    if manifest_path:
        p = Path(manifest_path)
        m_path = p if p.is_absolute() else root / p
    else:
        m_path = root / target_dir / "manifest.json"

    logger.debug("Loading dbt manifest from %s", m_path)
    if not m_path.exists():
        _run_dbt_parse(root)

    if not m_path.exists():
        from tff.core.exceptions import TffManifestNotFoundError

        raise TffManifestNotFoundError(
            f"dbt manifest not found at '{m_path}'. Please run 'dbt compile' first.",
            provider="dbt",
            path=m_path,
            hint="Run 'dbt compile' to generate target/manifest.json before running tff.",
        )

    if m_path.is_dir():
        import errno
        from tff.core.exceptions import normalize_os_error

        raise normalize_os_error(
            IsADirectoryError(errno.EISDIR, "Is a directory", str(m_path)),
            path=m_path,
            operation="read",
            expected_type="dbt manifest file",
            provider="dbt",
            hint=f"Expected '{m_path}' to be a JSON file, but found a directory.",
        )

    try:
        with open(m_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except OSError as exc:
        from tff.core.exceptions import normalize_os_error

        raise normalize_os_error(
            exc,
            path=m_path,
            operation="read",
            expected_type="dbt manifest file",
            provider="dbt",
        ) from exc
    except Exception as exc:
        from tff.core.exceptions import TffManifestError

        raise TffManifestError(
            f"Failed to parse dbt manifest at '{m_path}': {exc}",
            provider="dbt",
            path=m_path,
            hint="Ensure target/manifest.json contains valid JSON by re-running 'dbt compile'.",
            original_error=exc,
        ) from exc

    return manifest


def load_dbt_models(
    project_root: Path | Sequence[Path],
    target_dir: str = "target",
    dialect: str | None = None,
    max_workers: int | None = None,
    config: FitnessFunctionsConfig | None = None,
    manifest_path: str | Path | None = None,
) -> dict[str, ModelRepresentation]:
    roots = normalize_project_roots(project_root)
    if not roots:
        roots = [Path.cwd()]

    manifest_entries: list[tuple[Path, dict[str, Any]]] = []
    for root in roots:
        m_arg = manifest_path if len(roots) == 1 else None
        m_data = _load_single_manifest(root, target_dir=target_dir, manifest_path=m_arg)
        manifest_entries.append((root, m_data))

    # Auto-infer dialect from dbt adapter types if not explicitly provided
    adapter_types: set[str] = set()
    for _, manifest in manifest_entries:
        ad_type = manifest.get("metadata", {}).get("adapter_type")
        if ad_type:
            adapter_types.add(ad_type)

    if dialect is None:
        if len(adapter_types) > 1:
            raise ValueError(
                f"Conflicting dbt adapter types detected across projects: {sorted(adapter_types)}. "
                "Please specify a unified SQL dialect."
            )
        elif len(adapter_types) == 1:
            dialect = next(iter(adapter_types))

    logger.debug("Resolved dbt SQL dialect: %s (adapter_types: %s)", dialect, adapter_types)

    if not dialect:
        raise ValueError(
            "SQL dialect could not be determined. Please specify a dialect or ensure your dbt manifest contains adapter metadata."
        )

    # 1. Collect tests across all manifests by model unique ID
    model_tests: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for _, manifest in manifest_entries:
        for unique_id, node in manifest.get("nodes", {}).items():
            if node.get("resource_type") == "test":
                test_metadata = node.get("test_metadata", {})
                test_name = test_metadata.get("name")
                if not test_name:
                    continue
                if test_name == "unique":
                    test_name = "unique_values"

                depends_on_nodes = node.get("depends_on", {}).get("nodes", [])
                for dep in depends_on_nodes:
                    if dep.startswith("model.") or dep.startswith("seed."):
                        model_tests[dep].append((test_name, test_metadata.get("kwargs", {})))

    # 2. Unify parent_map and child_map across all manifests
    unified_parent_map: dict[str, list[str]] = defaultdict(list)
    unified_child_map: dict[str, list[str]] = defaultdict(list)
    for _, manifest in manifest_entries:
        for child_id, parents in manifest.get("parent_map", {}).items():
            for p in parents:
                if p not in unified_parent_map[child_id]:
                    unified_parent_map[child_id].append(p)
        for parent_id, children in manifest.get("child_map", {}).items():
            for c in children:
                if c not in unified_child_map[parent_id]:
                    unified_child_map[parent_id].append(c)

    # Ensure reciprocal DAG links
    for child_id, parents in list(unified_parent_map.items()):
        for p in parents:
            if child_id not in unified_child_map[p]:
                unified_child_map[p].append(child_id)
    for parent_id, children in list(unified_child_map.items()):
        for c in children:
            if parent_id not in unified_parent_map[c]:
                unified_parent_map[c].append(parent_id)

    # 3. Detect and resolve node unique ID clashes or cross-project references
    # Map (root, unique_id) -> effective_id
    id_mapping: dict[tuple[Path, str], str] = {}
    nodes_seen: dict[str, list[tuple[Path, dict[str, Any]]]] = defaultdict(list)

    for root, manifest in manifest_entries:
        for unique_id, node in manifest.get("nodes", {}).items():
            if node.get("resource_type") in ("model", "seed"):
                nodes_seen[unique_id].append((root, node))

    for unique_id, occurrences in nodes_seen.items():
        if len(occurrences) == 1:
            root, _ = occurrences[0]
            id_mapping[(root, unique_id)] = unique_id
        else:
            # Multiple occurrences across projects
            # Determine defining project vs imported stubs
            defining: list[tuple[Path, dict[str, Any]]] = []
            for root, node in occurrences:
                rel = (node.get("original_file_path") or "").strip()
                file_exists = bool(rel and (root / rel).is_file())
                has_code = bool(node.get("compiled_code") or node.get("raw_code"))
                if file_exists or has_code:
                    defining.append((root, node))

            if len(defining) == 1:
                # Exactly one defining model; others are cross-project stubs
                def_root, _ = defining[0]
                for r, _ in occurrences:
                    id_mapping[(r, unique_id)] = unique_id
            elif len(defining) == 0:
                # Synthetic/mock nodes without files or code
                for r, _ in occurrences:
                    id_mapping[(r, unique_id)] = unique_id
            else:
                # Genuine clash: multiple projects define different models with identical unique_id
                for r, _ in occurrences:
                    id_mapping[(r, unique_id)] = f"{r.name}:{unique_id}"

    # 4. Map nodes of type 'model' and 'seed' to ModelRepresentation
    mapped_models: dict[str, ModelRepresentation] = {}

    for root, manifest in manifest_entries:
        for unique_id, node in manifest.get("nodes", {}).items():
            resource_type = node.get("resource_type")
            if resource_type not in ("model", "seed"):
                continue

            eff_id = id_mapping.get((root, unique_id), unique_id)
            if eff_id in mapped_models:
                continue

            name = node.get("name", "")

            # Map column types
            columns_to_types = {}
            for col_name, col_meta in node.get("columns", {}).items():
                col_type = col_meta.get("data_type") or "unknown"
                columns_to_types[col_name.lower()] = col_type.lower()

            # Metadata parsing
            meta = node.get("meta", {})
            config_meta = node.get("config", {}).get("meta", {})
            owner = meta.get("owner") or config_meta.get("owner")

            grains_raw = (
                meta.get("grain")
                or meta.get("grains")
                or config_meta.get("grain")
                or config_meta.get("grains")
                or []
            )
            if isinstance(grains_raw, str):
                grains = [grains_raw]
            elif isinstance(grains_raw, list):
                grains = [str(g) for g in grains_raw]
            else:
                grains = []

            # Dependencies
            depends_on_raw = set(node.get("depends_on", {}).get("nodes", []))
            depends_on: set[str] = set()
            for dep in depends_on_raw:
                mapped_dep = id_mapping.get((root, dep), dep)
                if any(mapped_dep.startswith(pfx) for pfx in ("model.", "seed.", "source.")) or ":" in mapped_dep:
                    depends_on.add(mapped_dep)

            # Integrate parents from unified parent_map
            for p in unified_parent_map.get(unique_id, []):
                mapped_p = id_mapping.get((root, p), p)
                if any(mapped_p.startswith(pfx) for pfx in ("model.", "seed.", "source.")) or ":" in mapped_p:
                    depends_on.add(mapped_p)

            # Ephemeral models behave like symbolic models
            materialized = node.get("config", {}).get("materialized")
            if resource_type == "seed":
                materialized = "seed"
            elif not materialized:
                materialized = "view"

            is_symbolic = materialized == "ephemeral"

            rel_path = (node.get("original_file_path") or "").strip()
            abs_path = str(root / rel_path) if rel_path else ""

            audits = list(model_tests.get(unique_id, []))
            query = node.get("compiled_code") or node.get("raw_code")
            raw_code = node.get("raw_code")
            node_macros = node.get("depends_on", {}).get("macros", [])

            mapped_models[eff_id] = ModelRepresentation(
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
                query=query,
                raw_code=raw_code,
                materialized=materialized,
                expression=None,
                tags=node.get("tags") or [],
                meta={
                    **config_meta,
                    **meta,
                    "macro_dependencies": node_macros,
                    "parent_map": unified_parent_map.get(unique_id, []),
                    "child_map": unified_child_map.get(unique_id, []),
                },
                provider="dbt",
            )

    # 5. Map sources to ModelRepresentation so graph checks resolve them
    for root, manifest in manifest_entries:
        for source_id, source in manifest.get("sources", {}).items():
            if source_id in mapped_models:
                continue
            name = source.get("name", "")
            rel_path = (source.get("original_file_path") or "").strip()
            abs_path = str(root / rel_path) if rel_path else ""

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
                materialized="table",
                tags=source.get("tags") or [],
                meta={
                    **(source.get("meta") or {}),
                    "parent_map": unified_parent_map.get(source_id, []),
                    "child_map": unified_child_map.get(source_id, []),
                },
                provider="dbt",
            )

    # 6. Map exposures to ModelRepresentation
    for root, manifest in manifest_entries:
        for exposure_id, exposure in manifest.get("exposures", {}).items():
            if exposure_id in mapped_models:
                continue
            name = exposure.get("name", "")
            rel_path = (exposure.get("original_file_path") or "").strip()
            abs_path = str(root / rel_path) if rel_path else ""

            owner_meta = exposure.get("owner", {})
            owner = (
                owner_meta.get("name")
                or owner_meta.get("email")
                or exposure.get("meta", {}).get("owner")
            )
            exp_deps = set()
            for dep in exposure.get("depends_on", {}).get("nodes", []):
                mapped_dep = id_mapping.get((root, dep), dep)
                exp_deps.add(mapped_dep)
            for p in unified_parent_map.get(exposure_id, []):
                mapped_p = id_mapping.get((root, p), p)
                exp_deps.add(mapped_p)

            mapped_models[exposure_id] = ModelRepresentation(
                name=name,
                path=abs_path,
                dialect=dialect,
                is_symbolic=True,
                is_external=True,
                columns_to_types={},
                depends_on=exp_deps,
                description=exposure.get("description"),
                owner=owner,
                grains=[],
                audits=[],
                materialized="exposure",
                tags=exposure.get("tags") or [],
                meta={
                    **(exposure.get("meta") or {}),
                    "parent_map": unified_parent_map.get(exposure_id, []),
                    "child_map": unified_child_map.get(exposure_id, []),
                },
                provider="dbt",
            )

    # 7. Map metrics to ModelRepresentation
    for root, manifest in manifest_entries:
        for metric_id, metric in manifest.get("metrics", {}).items():
            if metric_id in mapped_models:
                continue
            name = metric.get("name", "")
            rel_path = (metric.get("original_file_path") or "").strip()
            abs_path = str(root / rel_path) if rel_path else ""

            owner = metric.get("meta", {}).get("owner")
            metric_deps = set()
            for dep in metric.get("depends_on", {}).get("nodes", []):
                mapped_dep = id_mapping.get((root, dep), dep)
                metric_deps.add(mapped_dep)
            for p in unified_parent_map.get(metric_id, []):
                mapped_p = id_mapping.get((root, p), p)
                metric_deps.add(mapped_p)

            mapped_models[metric_id] = ModelRepresentation(
                name=name,
                path=abs_path,
                dialect=dialect,
                is_symbolic=True,
                is_external=True,
                columns_to_types={},
                depends_on=metric_deps,
                description=metric.get("description"),
                owner=owner,
                grains=[],
                audits=[],
                materialized="metric",
                tags=metric.get("tags") or [],
                meta={
                    **(metric.get("meta") or {}),
                    "parent_map": unified_parent_map.get(metric_id, []),
                    "child_map": unified_child_map.get(metric_id, []),
                },
                provider="dbt",
            )

    logger.debug("Mapped %d models/seeds/sources/exposures/metrics from dbt manifest(s)", len(mapped_models))

    # Parallelize AST parsing and hydrate model expressions with disk caching
    precompute_model_asts(
        mapped_models,
        project_root=roots[0],
        config=config,
        max_workers=max_workers,
    )

    return mapped_models
