from __future__ import annotations

import ast
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

import yaml

from tff.core.model import ModelRepresentation

logger = logging.getLogger(__name__)


def get_dirty_files(project_root: Path) -> list[Path]:
    """Get the list of modified/untracked .sql and .yml files in the project via git."""
    try:
        # Get git root directory
        git_root_res = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )
        git_root = Path(git_root_res.stdout.strip())

        # Get git status porcelain output
        res = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        )

        dirty_paths = []
        for line in res.stdout.splitlines():
            if not line or len(line) < 4:
                continue
            # Extract path (from index 3 onwards)
            rel_path_str = line[3:].strip()
            # If path was renamed, it might look like "R  old -> new"
            if " -> " in rel_path_str:
                rel_path_str = rel_path_str.split(" -> ")[-1].strip()
            # Clean quotes if any
            if rel_path_str.startswith('"') and rel_path_str.endswith('"'):
                rel_path_str = rel_path_str[1:-1]

            abs_path = (git_root / rel_path_str).resolve()
            if abs_path.exists() and abs_path.is_file():
                try:
                    # Check if it's under project_root
                    abs_path.relative_to(project_root.resolve())
                    if abs_path.suffix in (".sql", ".yml", ".yaml"):
                        dirty_paths.append(abs_path)
                except ValueError:
                    continue
        return dirty_paths
    except Exception as e:
        raise RuntimeError(f"Failed to detect git repository or run git commands: {e}")


def get_dirty_model_names(dirty_files: list[Path], project_root: Path) -> set[str]:
    """Extract model names affected by the modified files."""
    dirty_names = set()
    for df in dirty_files:
        if df.suffix == ".sql":
            dirty_names.add(df.name[:-4])
        elif df.suffix in (".yml", ".yaml"):
            try:
                with open(df, encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                for entry in data.get("models", []):
                    if isinstance(entry, dict) and "name" in entry:
                        dirty_names.add(entry["name"])
                for entry in data.get("seeds", []):
                    if isinstance(entry, dict) and "name" in entry:
                        dirty_names.add(entry["name"])
            except Exception:
                pass
    return dirty_names


def _parse_dbt_project_config(project_root: Path) -> tuple[str, list[str], list[str]]:
    """Parse dbt_project.yml to get the project name, model paths, and seed paths."""
    project_name = "unknown"
    model_paths = ["models"]
    seed_paths = ["seeds"]

    dbt_project_path = project_root / "dbt_project.yml"
    if dbt_project_path.exists():
        try:
            with open(dbt_project_path, encoding="utf-8") as f:
                dbt_config = yaml.safe_load(f) or {}
                project_name = dbt_config.get("name") or "unknown"

                m_paths = dbt_config.get("model-paths") or dbt_config.get("source-paths") or ["models"]
                if isinstance(m_paths, str):
                    model_paths = [m_paths]
                elif isinstance(m_paths, list):
                    model_paths = m_paths

                s_paths = dbt_config.get("seed-paths") or dbt_config.get("data-paths") or ["seeds"]
                if isinstance(s_paths, str):
                    seed_paths = [s_paths]
                elif isinstance(s_paths, list):
                    seed_paths = s_paths
        except Exception:
            pass

    return project_name, model_paths, seed_paths


def parse_dbt_sql_file(
    file_path: Path,
    project_root: Path,
    project_name: str,
    dialect: str | None = None,
) -> ModelRepresentation:
    """Parse a single dbt .sql file to build a ModelRepresentation (pre-compile)."""
    try:
        sql = file_path.read_text(encoding="utf-8")
    except Exception:
        sql = ""

    model_name = file_path.stem
    abs_path = str(file_path.resolve())

    # Extract configs using AST parsing on config(...) content
    config_data: dict[str, Any] = {}
    config_pattern = r"\{\{[\s\S]*?config\s*\(([\s\S]*?)\)[\s\S]*?\}\}"
    for match in re.finditer(config_pattern, sql):
        config_args = match.group(1).strip()
        try:
            tree = ast.parse(f"config({config_args})")
            call_node = tree.body[0].value
            if isinstance(call_node, ast.Call):
                for kw in call_node.keywords:
                    name = kw.arg
                    val = kw.value
                    if name:
                        try:
                            config_data[name] = ast.literal_eval(val)
                        except Exception:
                            pass
        except Exception:
            pass

    # Extract refs and sources via regex
    ref_pattern = r"ref\s*\(\s*['\"]([^'\"]+)['\"]\s*(?:,\s*['\"]([^'\"]+)['\"]\s*)?\)"
    raw_refs = []
    for match in re.finditer(ref_pattern, sql):
        g1 = match.group(1)
        g2 = match.group(2)
        if g2:
            raw_refs.append((g1, g2))
        else:
            raw_refs.append((None, g1))

    source_pattern = r"source\s*\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)"
    raw_sources = []
    for match in re.finditer(source_pattern, sql):
        raw_sources.append((match.group(1), match.group(2)))

    meta = config_data.get("meta", {})
    materialized = config_data.get("materialized", "view")
    is_symbolic = materialized == "ephemeral"
    tags = config_data.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    owner = config_data.get("owner") or meta.get("owner")

    grains_raw = (
        config_data.get("grain")
        or config_data.get("grains")
        or meta.get("grain")
        or meta.get("grains")
        or []
    )
    if isinstance(grains_raw, str):
        grains = [grains_raw]
    elif isinstance(grains_raw, list):
        grains = [str(g) for g in grains_raw]
    else:
        grains = []

    # Compile-time expression parsing fallback
    import sqlglot
    from tff.core.utils.jinja import clean_jinja_for_parsing

    expression = None
    if sql:
        try:
            cleaned_sql = clean_jinja_for_parsing(sql)
            expression = sqlglot.parse_one(cleaned_sql, read=dialect)
        except Exception:
            pass

    rep = ModelRepresentation(
        name=model_name,
        path=abs_path,
        dialect=dialect or "unknown",
        is_symbolic=is_symbolic,
        is_external=False,
        columns_to_types={},
        depends_on=set(),
        description=None,
        owner=owner,
        grains=grains,
        audits=[],
        query=sql,
        materialized=materialized,
        expression=expression,
        tags=tags,
        meta={
            **config_data,
            "_raw_refs": raw_refs,
            "_raw_sources": raw_sources,
        },
    )
    return rep


def parse_dbt_yml_file(
    file_path: Path,
    project_name: str,
    dialect: str,
    models: dict[str, ModelRepresentation],
) -> None:
    """Parse a dbt .yml property file and update the loaded models and sources."""
    try:
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        return

    for resource_key in ("models", "seeds"):
        for entry in data.get(resource_key, []):
            if not isinstance(entry, dict) or "name" not in entry:
                continue
            name = entry["name"]

            prefix = "model" if resource_key == "models" else "seed"
            unique_id = f"{prefix}.{project_name}.{name}"

            model_rep = models.get(unique_id)
            if not model_rep:
                continue

            if "description" in entry:
                model_rep.description = entry["description"]

            tags = entry.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            model_rep.tags = list(set(model_rep.tags + tags))

            meta = entry.get("meta") or {}
            config = entry.get("config") or {}
            config_meta = config.get("meta") or {}

            model_rep.meta = {**model_rep.meta, **config, **config_meta, **meta}

            owner = (
                meta.get("owner")
                or config_meta.get("owner")
                or config.get("owner")
                or entry.get("owner")
            )
            if owner:
                model_rep.owner = owner

            grains_raw = (
                meta.get("grain")
                or meta.get("grains")
                or config_meta.get("grain")
                or config_meta.get("grains")
                or config.get("grain")
                or config.get("grains")
                or entry.get("grain")
                or entry.get("grains")
            )
            if grains_raw is not None:
                if isinstance(grains_raw, str):
                    model_rep.grains = [grains_raw]
                elif isinstance(grains_raw, list):
                    model_rep.grains = [str(g) for g in grains_raw]

            if "materialized" in config:
                model_rep.materialized = config["materialized"]
                if model_rep.materialized == "ephemeral":
                    model_rep.is_symbolic = True

            for col in entry.get("columns", []):
                if not isinstance(col, dict) or "name" not in col:
                    continue
                col_name = col["name"].lower()
                if "data_type" in col and col["data_type"]:
                    model_rep.columns_to_types[col_name] = col["data_type"].lower()

                for test in col.get("tests", []):
                    test_name = None
                    test_kwargs = {}
                    if isinstance(test, str):
                        test_name = test
                    elif isinstance(test, dict) and test:
                        test_name = list(test.keys())[0]
                        test_kwargs = test[test_name] or {}

                    if test_name:
                        if test_name == "unique":
                            test_name = "unique_values"
                        if "column_name" not in test_kwargs:
                            test_kwargs["column_name"] = col["name"]
                        model_rep.audits.append((test_name, test_kwargs))

            for test in entry.get("tests", []):
                test_name = None
                test_kwargs = {}
                if isinstance(test, str):
                    test_name = test
                elif isinstance(test, dict) and test:
                    test_name = list(test.keys())[0]
                    test_kwargs = test[test_name] or {}

                if test_name:
                    if test_name == "unique":
                        test_name = "unique_values"
                    model_rep.audits.append((test_name, test_kwargs))

    for src in data.get("sources", []):
        if not isinstance(src, dict) or "name" not in src:
            continue
        source_name = src["name"]
        source_tags = src.get("tags") or []
        if isinstance(source_tags, str):
            source_tags = [source_tags]
        source_meta = src.get("meta") or {}
        source_owner = source_meta.get("owner")

        for tbl in src.get("tables", []):
            if not isinstance(tbl, dict) or "name" not in tbl:
                continue
            table_name = tbl["name"]
            unique_id = f"source.{project_name}.{source_name}.{table_name}"

            tbl_tags = tbl.get("tags") or []
            if isinstance(tbl_tags, str):
                tbl_tags = [tbl_tags]
            all_tags = list(set(source_tags + tbl_tags))

            tbl_meta = tbl.get("meta") or {}
            all_meta = {**source_meta, **tbl_meta}
            owner = tbl_meta.get("owner") or source_owner

            models[unique_id] = ModelRepresentation(
                name=table_name,
                path=str(file_path.resolve()),
                dialect=dialect,
                is_symbolic=True,
                is_external=True,
                columns_to_types={},
                depends_on=set(),
                description=tbl.get("description"),
                owner=owner,
                grains=[],
                audits=[],
                materialized="table",
                tags=all_tags,
                meta=all_meta,
            )


def load_dbt_models_fallback(
    project_root: Path,
    dialect: str | None = None,
) -> dict[str, ModelRepresentation]:
    """Fallback loader for dbt projects that parses files on the fly (pre-compile)."""
    if not dialect:
        raise ValueError(
            "SQL dialect could not be determined. Please specify a dialect or ensure your dbt manifest contains adapter metadata."
        )

    project_name, model_paths, seed_paths = _parse_dbt_project_config(project_root)
    models: dict[str, ModelRepresentation] = {}

    # 1. Load all .sql files
    for model_path_str in model_paths:
        model_dir = project_root / model_path_str
        if model_dir.exists():
            for sql_file in model_dir.rglob("*.sql"):
                if sql_file.name.startswith("."):
                    continue
                unique_id = f"model.{project_name}.{sql_file.stem}"
                models[unique_id] = parse_dbt_sql_file(
                    sql_file, project_root, project_name, dialect
                )

    # 2. Load all seeds (.csv files)
    for seed_path_str in seed_paths:
        seed_dir = project_root / seed_path_str
        if seed_dir.exists():
            for csv_file in seed_dir.rglob("*.csv"):
                if csv_file.name.startswith("."):
                    continue
                seed_name = csv_file.stem
                unique_id = f"seed.{project_name}.{seed_name}"
                models[unique_id] = ModelRepresentation(
                    name=seed_name,
                    path=str(csv_file.resolve()),
                    dialect=dialect,
                    is_symbolic=False,
                    is_external=False,
                    columns_to_types={},
                    depends_on=set(),
                    description=None,
                    owner=None,
                    grains=[],
                    audits=[],
                    query=None,
                    materialized="seed",
                    expression=None,
                    tags=[],
                    meta={},
                )

    # 3. Load/merge metadata from all .yml and .yaml files under model and seed paths
    for path_str in list(model_paths) + list(seed_paths):
        directory = project_root / path_str
        if directory.exists():
            for yml_file in directory.rglob("*"):
                if yml_file.suffix in (".yml", ".yaml"):
                    if yml_file.name.startswith("."):
                        continue
                    parse_dbt_yml_file(yml_file, project_name, dialect, models)

    # 4. Resolve depends_on (raw_refs and raw_sources)
    for model in models.values():
        if model.is_external:
            continue
        raw_refs = model.meta.pop("_raw_refs", [])
        raw_sources = model.meta.pop("_raw_sources", [])

        depends_on = set()

        for package, ref_name in raw_refs:
            ref_pkg = package or project_name
            seed_uid = f"seed.{ref_pkg}.{ref_name}"
            model_uid = f"model.{ref_pkg}.{ref_name}"
            if seed_uid in models:
                depends_on.add(seed_uid)
            elif model_uid in models:
                depends_on.add(model_uid)
            else:
                depends_on.add(model_uid)

        for src_name, tbl_name in raw_sources:
            depends_on.add(f"source.{project_name}.{src_name}.{tbl_name}")

        model.depends_on = depends_on

    return models


def _load_dbt_models_from_manifest(
    manifest: dict,
    project_root: Path,
    dialect: str,
) -> dict[str, ModelRepresentation]:
    # 1. Collect tests by model unique ID
    model_tests: dict[str, list[tuple[str, dict]]] = {}
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
        depends_on = set(node.get("depends_on", {}).get("nodes", []))
        depends_on = {
            dep
            for dep in depends_on
            if dep.startswith("model.") or dep.startswith("seed.") or dep.startswith("source.")
        }

        # Ephemeral models behave like symbolic models
        materialized = node.get("config", {}).get("materialized")
        if resource_type == "seed":
            materialized = "seed"
        elif not materialized:
            materialized = "view"

        is_symbolic = materialized == "ephemeral"

        rel_path = node.get("original_file_path", "")
        abs_path = str(project_root / rel_path)

        audits = model_tests.get(unique_id, [])
        query = node.get("compiled_code") or node.get("raw_code")

        expression = None
        if query:
            try:
                import sqlglot

                expression = sqlglot.parse_one(query, read=dialect)
            except Exception:
                pass

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
            query=query,
            materialized=materialized,
            expression=expression,
            tags=node.get("tags") or [],
            meta={**config_meta, **meta},
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
            materialized="table",
            tags=source.get("tags") or [],
            meta=source.get("meta") or {},
        )

    return mapped_models


def load_dbt_models(
    project_root: Path,
    target_dir: str = "target",
    dialect: str | None = None,
    dirty: bool = False,
) -> dict[str, ModelRepresentation]:
    manifest_path = project_root / target_dir / "manifest.json"

    if not manifest_path.exists():
        if dirty:
            # Fall back to parsing the codebase directly in dirty mode
            return load_dbt_models_fallback(project_root, dialect)
        raise FileNotFoundError(
            f"dbt manifest not found at {manifest_path}. Please run 'dbt compile' first."
        )

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    # Auto-infer dialect from dbt adapter type if not explicitly provided
    adapter_type = manifest.get("metadata", {}).get("adapter_type")
    if dialect is None:
        dialect = adapter_type

    if not dialect:
        raise ValueError(
            "SQL dialect could not be determined. Please specify a dialect or ensure your dbt manifest contains adapter metadata."
        )

    models = _load_dbt_models_from_manifest(manifest, project_root, dialect)

    if dirty:
        dirty_files = get_dirty_files(project_root)
        project_name, _, _ = _parse_dbt_project_config(project_root)

        # Overlay SQL files first
        for df in dirty_files:
            if df.suffix == ".sql":
                abs_path = str(df.resolve())
                # Find matching model in models by path
                existing_uid = None
                for uid, m in models.items():
                    if m.path and Path(m.path).resolve() == Path(abs_path).resolve():
                        existing_uid = uid
                        break

                new_model = parse_dbt_sql_file(df, project_root, project_name, dialect)
                if existing_uid:
                    models[existing_uid] = new_model
                else:
                    uid = f"model.{project_name}.{df.stem}"
                    models[uid] = new_model

        # Overlay YAML files
        for df in dirty_files:
            if df.suffix in (".yml", ".yaml"):
                parse_dbt_yml_file(df, project_name, dialect, models)

        # Re-resolve depends_on for any newly loaded/updated models
        for model in models.values():
            if "_raw_refs" in model.meta or "_raw_sources" in model.meta:
                raw_refs = model.meta.pop("_raw_refs", [])
                raw_sources = model.meta.pop("_raw_sources", [])

                depends_on = set()
                for package, ref_name in raw_refs:
                    ref_pkg = package or project_name
                    seed_uid = f"seed.{ref_pkg}.{ref_name}"
                    model_uid = f"model.{ref_pkg}.{ref_name}"
                    if seed_uid in models:
                        depends_on.add(seed_uid)
                    else:
                        depends_on.add(model_uid)

                for src_name, tbl_name in raw_sources:
                    depends_on.add(f"source.{project_name}.{src_name}.{tbl_name}")

                model.depends_on = depends_on

    return models
