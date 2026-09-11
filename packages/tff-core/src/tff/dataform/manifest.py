"""Manifest and project loader for Google Cloud Dataform projects."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml

from tff.core.model import ModelRepresentation
from tff.core.utils.jinja import clean_dataform_for_parsing

logger = logging.getLogger(__name__)

CANDIDATE_MANIFEST_FILES = [
    "compilation_result.json",
    "compilation-result.json",
    "manifest.json",
    "dataform-compiled.json",
    "target/compilation_result.json",
    "target/manifest.json",
]


def _load_settings(project_root: Path) -> dict[str, Any]:
    """Load settings from workflow_settings.yaml or dataform.json if present."""
    yaml_path = project_root / "workflow_settings.yaml"
    if yaml_path.is_file():
        try:
            content = yaml_path.read_text(encoding="utf-8")
            data = yaml.safe_load(content)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.debug("Failed to read workflow_settings.yaml: %s", e)

    json_path = project_root / "dataform.json"
    if json_path.is_file():
        try:
            content = json_path.read_text(encoding="utf-8")
            data = json.loads(content)
            if isinstance(data, dict):
                return data
        except Exception as e:
            logger.debug("Failed to read dataform.json: %s", e)

    return {}


def _find_manifest_file(project_root: Path, manifest_path: Path | str | None = None) -> Path | None:
    """Find a pre-existing Dataform compilation manifest file."""
    if manifest_path:
        p = Path(manifest_path)
        if not p.is_absolute():
            p = project_root / p
        if p.is_file():
            return p
        raise FileNotFoundError(f"Specified Dataform manifest not found at: {p}")

    for candidate in CANDIDATE_MANIFEST_FILES:
        candidate_path = project_root / candidate
        if candidate_path.is_file():
            return candidate_path
    return None


def _compile_via_cli(project_root: Path) -> dict[str, Any] | None:
    """Attempt to compile Dataform project using local CLI (dataform or npx @dataform/cli)."""
    cmd = None
    if shutil.which("dataform"):
        cmd = ["dataform", "compile", "--json"]
    elif shutil.which("npx"):
        cmd = ["npx", "--no-install", "@dataform/cli", "compile", "--json"]

    if not cmd:
        return None

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return json.loads(proc.stdout)
    except Exception as e:
        logger.debug("CLI compilation invocation failed: %s", e)
    return None


def _target_key(target: dict[str, Any] | None) -> str:
    """Return canonical lookup key for a Target object."""
    if not target:
        return ""
    name = target.get("name", "")
    schema = target.get("schema", "")
    return f"{schema}.{name}" if schema else name


def _parse_compiled_graph(
    graph_data: dict[str, Any],
    project_root: Path,
    dialect: str = "bigquery",
) -> dict[str, ModelRepresentation]:
    """Parse a compiled Dataform graph into ModelRepresentation objects.

    Supports both CLI JSON format (tables, assertions, declarations) and
    Google Cloud REST API compilationResultActions format.
    """
    mapped_models: dict[str, ModelRepresentation] = {}
    model_audits: dict[str, list[tuple[str, dict]]] = {}

    # Format B: GCP REST API compilationResultActions
    if "compilationResultActions" in graph_data:
        actions = graph_data.get("compilationResultActions", [])
        tables_list: list[dict[str, Any]] = []
        assertions_list: list[dict[str, Any]] = []
        declarations_list: list[dict[str, Any]] = []

        for act in actions:
            target = act.get("target") or {}
            rel = act.get("relation")
            assertion = act.get("assertion")
            declaration = act.get("declaration")
            file_path = act.get("filePath") or ""

            if rel:
                rel_type = rel.get("relationType", "TABLE").lower()
                if "view" in rel_type:
                    m_type = "view"
                elif "incremental" in rel_type:
                    m_type = "incremental"
                else:
                    m_type = "table"

                tables_list.append({
                    "target": target,
                    "type": m_type,
                    "query": rel.get("selectQuery", ""),
                    "fileName": file_path,
                    "actionDescriptor": rel.get("actionDescriptor", {}),
                    "dependencyTargets": rel.get("dependencyTargets", []),
                    "disabled": rel.get("disabled", False),
                })
            elif assertion:
                assertions_list.append({
                    "target": target,
                    "parentAction": assertion.get("parentAction"),
                    "dependencyTargets": assertion.get("dependencyTargets", []),
                    "query": assertion.get("selectQuery", ""),
                    "fileName": file_path,
                    "actionDescriptor": assertion.get("actionDescriptor", {}),
                })
            elif declaration:
                declarations_list.append({
                    "target": target,
                    "actionDescriptor": declaration.get("actionDescriptor", {}),
                    "fileName": file_path,
                })
    else:
        # Format A: Dataform CLI output
        tables_list = graph_data.get("tables", [])
        assertions_list = graph_data.get("assertions", [])
        declarations_list = graph_data.get("declarations", [])

    # 1. Process assertions to map tests/audits to parent actions
    for assertion in assertions_list:
        parent_action = assertion.get("parentAction")
        parent_key = _target_key(parent_action)
        desc = assertion.get("actionDescriptor", {}).get("description", "")
        target_name = assertion.get("target", {}).get("name", "")

        test_name = "assertion"
        test_kwargs: dict[str, Any] = {}
        if "uniqueKey" in target_name or "uniqueKey" in desc:
            test_name = "unique_values"
        elif "nonNull" in target_name or "nonNull" in desc:
            test_name = "not_null"
        elif "rowConditions" in target_name or "rowConditions" in desc:
            test_name = "row_conditions"

        # If parent_action is known, associate with it
        if parent_key:
            model_audits.setdefault(parent_key, []).append((test_name, test_kwargs))
        else:
            # Check dependencyTargets
            for dep in assertion.get("dependencyTargets", []):
                dep_key = _target_key(dep)
                if dep_key:
                    model_audits.setdefault(dep_key, []).append((test_name, test_kwargs))

    # 2. Map tables and views
    for table in tables_list:
        if table.get("disabled", False):
            continue

        target = table.get("target", {})
        name = target.get("name", "")
        key = _target_key(target)
        if not key:
            key = name

        # Materialization
        raw_type = str(table.get("type") or table.get("enumType") or "table").lower()
        if "view" in raw_type:
            materialized = "view"
        elif "incremental" in raw_type:
            materialized = "incremental"
        elif "inline" in raw_type:
            materialized = "inline"
        else:
            materialized = "table"

        is_symbolic = materialized == "inline"

        # Columns and types
        action_desc = table.get("actionDescriptor", {}) or {}
        columns_to_types: dict[str, str] = {}
        for col in action_desc.get("columns", []):
            path_parts = col.get("path", [])
            if path_parts:
                col_name = path_parts[0].lower()
                columns_to_types[col_name] = col.get("type", "unknown").lower()

        # Labels / Owner / Tags
        bigquery_config = table.get("bigquery", {}) or {}
        bq_labels = (
            action_desc.get("bigqueryLabels")
            or bigquery_config.get("labels")
            or {}
        )
        owner = bq_labels.get("owner")
        tags = table.get("tags") or []

        # Grains / Unique key
        unique_keys = table.get("uniqueKey") or table.get("unique_key") or []
        if isinstance(unique_keys, str):
            grains = [unique_keys]
        elif isinstance(unique_keys, list):
            grains = [str(k) for k in unique_keys]
        else:
            grains = []

        # Dependencies
        depends_on: set[str] = set()
        for dep in table.get("dependencyTargets", []):
            dep_key = _target_key(dep)
            if dep_key:
                depends_on.add(dep_key)

        # Audits
        audits = list(model_audits.get(key, []))
        if grains and not any(t[0] == "unique_values" for t in audits):
            audits.append(("unique_values", {"columns": grains}))

        # Paths
        file_name = table.get("fileName", "")
        abs_path = str(project_root / file_name) if file_name else ""

        # Query and AST
        query = table.get("query")
        expression = None
        if query:
            try:
                import sqlglot
                expression = sqlglot.parse_one(query, read=dialect)
            except Exception:
                pass

        mapped_models[key] = ModelRepresentation(
            name=name,
            path=abs_path,
            dialect=dialect,
            is_symbolic=is_symbolic,
            is_external=False,
            columns_to_types=columns_to_types,
            depends_on=depends_on,
            description=action_desc.get("description"),
            owner=owner,
            grains=grains,
            audits=audits,
            query=query,
            materialized=materialized,
            expression=expression,
            tags=tags,
            meta={**bq_labels},
        )

    # 3. Map declarations (external sources)
    for decl in declarations_list:
        target = decl.get("target", {})
        name = target.get("name", "")
        key = _target_key(target) or name
        action_desc = decl.get("actionDescriptor", {}) or {}
        file_name = decl.get("fileName", "")
        abs_path = str(project_root / file_name) if file_name else ""

        mapped_models[key] = ModelRepresentation(
            name=name,
            path=abs_path,
            dialect=dialect,
            is_symbolic=True,
            is_external=True,
            columns_to_types={},
            depends_on=set(),
            description=action_desc.get("description"),
            owner=action_desc.get("bigqueryLabels", {}).get("owner"),
            grains=[],
            audits=[],
            materialized="table",
            tags=decl.get("tags") or [],
            meta={},
        )

    # Ensure dependencies that refer to un-prefixed names resolve if possible
    _resolve_dependencies_keys(mapped_models)

    return mapped_models


def _resolve_dependencies_keys(models: dict[str, ModelRepresentation]) -> None:
    """Normalize dependencies so keys in model.depends_on match keys in models."""
    name_to_keys: dict[str, list[str]] = {}
    for key, model in models.items():
        name_to_keys.setdefault(model.name, []).append(key)

    for model in models.values():
        normalized_deps = set()
        for dep in model.depends_on:
            if dep in models:
                normalized_deps.add(dep)
            elif dep in name_to_keys and len(name_to_keys[dep]) == 1:
                normalized_deps.add(name_to_keys[dep][0])
            else:
                normalized_deps.add(dep)
        model.depends_on = normalized_deps


def _parse_sqlx_config(content: str) -> tuple[dict[str, Any], str]:
    """Extract and parse the config { ... } block from a .sqlx file."""
    match = re.search(r"^\s*config\s*\{", content, re.MULTILINE | re.IGNORECASE)
    if not match:
        return {}, content

    brace_start = match.end() - 1
    depth = 0
    in_quote = None
    end = -1

    for i in range(brace_start, len(content)):
        ch = content[i]
        if in_quote:
            if ch == "\\" and i + 1 < len(content):
                continue
            if ch == in_quote:
                in_quote = None
        elif ch in ("'", '"', "`"):
            in_quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break

    if end == -1:
        return {}, content

    config_str = content[brace_start:end]
    remaining_sql = content[:match.start()] + content[end:]

    # Clean config_str to be valid YAML
    cleaned_yaml = re.sub(r"//.*", "", config_str)
    cleaned_yaml = re.sub(r"/\*.*?\*/", "", cleaned_yaml, flags=re.DOTALL)
    cleaned_yaml = re.sub(r",\s*([}\]])", r"\1", cleaned_yaml)

    try:
        parsed = yaml.safe_load(cleaned_yaml)
        if isinstance(parsed, dict):
            return parsed, remaining_sql
    except Exception as e:
        logger.debug("Failed to parse .sqlx config YAML: %s", e)

    return {}, content


def _extract_sqlx_refs(sql: str) -> list[tuple[str | None, str]]:
    """Extract referenced models from ${ref(...)} expressions."""
    refs = []
    # 1. Two-argument: ${ref("schema", "name")}
    for match in re.finditer(r"\$\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*,\s*['\"]([^'\"]+)['\"]\s*\)\s*\}", sql):
        refs.append((match.group(1), match.group(2)))

    # 2. One-argument: ${ref("name")}
    for match in re.finditer(r"\$\{\s*ref\(\s*['\"]([^'\"]+)['\"]\s*\)\s*\}", sql):
        refs.append((None, match.group(1)))

    # 3. Object argument: ${ref({ schema: "...", name: "..." })}
    for match in re.finditer(r"\$\{\s*ref\(\s*\{[^}]*name\s*:\s*['\"]([^'\"]+)['\"][^}]*\}\s*\)\s*\}", sql):
        refs.append((None, match.group(1)))

    return refs


def _load_models_from_sources(
    project_root: Path,
    settings: dict[str, Any],
    dialect: str = "bigquery",
) -> dict[str, ModelRepresentation]:
    """Parse Dataform models directly from definitions/ directory."""
    mapped_models: dict[str, ModelRepresentation] = {}
    definitions_dir = project_root / "definitions"
    search_dirs = [definitions_dir] if definitions_dir.is_dir() else [project_root]

    default_schema = (
        settings.get("defaultDataset")
        or settings.get("defaultSchema")
        or ""
    )

    # 1. Search for .sqlx files
    sqlx_files: list[Path] = []
    for s_dir in search_dirs:
        sqlx_files.extend(s_dir.rglob("*.sqlx"))

    for sqlx_path in sqlx_files:
        try:
            content = sqlx_path.read_text(encoding="utf-8")
        except Exception:
            continue

        config, remaining_sql = _parse_sqlx_config(content)
        stem_name = sqlx_path.stem
        name = str(config.get("name") or stem_name)
        schema = str(config.get("schema") or default_schema)
        key = f"{schema}.{name}" if schema else name

        raw_type = str(config.get("type", "view")).lower()
        if raw_type in ("table", "incremental", "view", "inline"):
            materialized = raw_type
        else:
            materialized = "view"

        is_symbolic = materialized == "inline" or raw_type == "declaration"
        is_external = raw_type == "declaration"

        # Dependencies
        depends_on = set()
        for ref_schema, ref_name in _extract_sqlx_refs(remaining_sql):
            dep_key = f"{ref_schema}.{ref_name}" if ref_schema else ref_name
            depends_on.add(dep_key)

        for dep in config.get("dependencies", []):
            depends_on.add(str(dep))

        # Description and owner
        description = config.get("description")
        meta = config.get("bigquery", {}) or {}
        owner = meta.get("labels", {}).get("owner") or config.get("owner")

        # Columns
        columns_to_types = {}
        for col_name, col_info in (config.get("columns") or {}).items():
            col_type = "unknown"
            if isinstance(col_info, dict):
                col_type = col_info.get("type", "unknown")
            columns_to_types[col_name.lower()] = str(col_type).lower()

        # Grains and Audits
        assertions = config.get("assertions") or {}
        unique_keys = assertions.get("uniqueKey") or config.get("uniqueKey") or []
        if isinstance(unique_keys, str):
            grains = [unique_keys]
        elif isinstance(unique_keys, list):
            grains = [str(k) for k in unique_keys]
        else:
            grains = []

        audits: list[tuple[str, dict]] = []
        if grains:
            audits.append(("unique_values", {"columns": grains}))
        for col in (assertions.get("nonNull") or []):
            audits.append(("not_null", {"columns": [str(col)]}))

        # Query & AST
        cleaned_sql = clean_dataform_for_parsing(content)
        expression = None
        try:
            import sqlglot
            expression = sqlglot.parse_one(cleaned_sql, read=dialect)
        except Exception:
            pass

        mapped_models[key] = ModelRepresentation(
            name=name,
            path=str(sqlx_path.resolve()),
            dialect=dialect,
            is_symbolic=is_symbolic,
            is_external=is_external,
            columns_to_types=columns_to_types,
            depends_on=depends_on,
            description=description,
            owner=owner,
            grains=grains,
            audits=audits,
            query=remaining_sql,
            materialized=materialized,
            expression=expression,
            tags=config.get("tags") or [],
            meta=meta,
        )

    # 2. Search for declarations in .js files
    js_files: list[Path] = []
    for s_dir in search_dirs:
        js_files.extend(s_dir.rglob("*.js"))

    for js_path in js_files:
        try:
            js_content = js_path.read_text(encoding="utf-8")
        except Exception:
            continue

        for decl_match in re.finditer(r"declare\s*\(\s*(\{.*?\})\s*\)", js_content, re.DOTALL):
            raw_decl = decl_match.group(1)
            raw_decl = re.sub(r"//.*", "", raw_decl)
            raw_decl = re.sub(r",\s*([}\]])", r"\1", raw_decl)
            try:
                decl_info = yaml.safe_load(raw_decl)
                if isinstance(decl_info, dict):
                    decl_name = decl_info.get("name", "")
                    decl_schema = decl_info.get("schema", default_schema)
                    decl_key = f"{decl_schema}.{decl_name}" if decl_schema else decl_name
                    if decl_key and decl_key not in mapped_models:
                        mapped_models[decl_key] = ModelRepresentation(
                            name=decl_name,
                            path=str(js_path.resolve()),
                            dialect=dialect,
                            is_symbolic=True,
                            is_external=True,
                            columns_to_types={},
                            depends_on=set(),
                            description=decl_info.get("description"),
                            owner=decl_info.get("owner"),
                            grains=[],
                            audits=[],
                            materialized="table",
                            tags=decl_info.get("tags") or [],
                            meta={},
                        )
            except Exception:
                pass

    _resolve_dependencies_keys(mapped_models)
    return mapped_models


def load_dataform_models(
    project_root: Path,
    manifest_path: Path | str | None = None,
    dialect: str | None = None,
) -> dict[str, ModelRepresentation]:
    """Load Dataform models via precompiled JSON, CLI compilation, or direct source parsing."""
    settings = _load_settings(project_root)
    if dialect is None:
        warehouse = settings.get("warehouse") or settings.get("defaultLocation")
        dialect = "bigquery" if not warehouse else str(warehouse).lower()

    # Tier 1: Check for precompiled manifest
    manifest_file = _find_manifest_file(project_root, manifest_path)
    if manifest_file:
        try:
            with open(manifest_file, encoding="utf-8") as f:
                data = json.load(f)
            return _parse_compiled_graph(data, project_root, dialect=dialect)
        except Exception as e:
            if manifest_path:
                raise e
            logger.warning("Failed to parse manifest file %s: %s", manifest_file, e)

    # Tier 2: Check for local CLI compilation
    compiled_data = _compile_via_cli(project_root)
    if compiled_data:
        try:
            return _parse_compiled_graph(compiled_data, project_root, dialect=dialect)
        except Exception as e:
            logger.debug("Failed to parse CLI compilation output: %s", e)

    # Tier 3: Direct static source parsing
    return _load_models_from_sources(project_root, settings, dialect=dialect)
