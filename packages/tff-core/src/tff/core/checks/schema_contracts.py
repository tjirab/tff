"""Cross-model schema contract parity checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from tff.core.config import (
    FitnessFunctionsConfig,
    _ensure_under_root,
    resolve_project_path,
)
from tff.core.report import LintFinding
from tff.core.utils.schema_contract_utils import (
    check_column_list_parity,
    check_dimension_set_parity,
    extract_final_select_columns,
    normalize_columns,
    read_model_sql,
)

if TYPE_CHECKING:
    from tff.core.model import ModelRepresentation


def _resolve_path(project_root: Path, models_dir: str, filename: str) -> Path:
    return _ensure_under_root(project_root / models_dir / filename, project_root)


def _get_model_sql_and_path(
    project_root: Path,
    models_dir: str,
    filename: str,
    models: dict[str, ModelRepresentation] | None = None,
) -> tuple[str | None, str]:
    """Retrieve SQL query and model path from ModelRepresentation or disk."""
    if models:
        clean_file = Path(filename).name
        model_stem = Path(filename).stem
        for name, model in models.items():
            model_path = getattr(model, "path", None)
            matched = False
            if model_path:
                norm_path = model_path.replace("\\", "/")
                target_subpath = f"{models_dir}/{filename}".replace("\\", "/").strip("/")
                if (
                    norm_path.endswith(target_subpath)
                    or norm_path.endswith(f"/{clean_file}")
                    or Path(model_path).name == clean_file
                ):
                    matched = True
            if not matched and (name == model_stem or name == clean_file or name == filename):
                matched = True

            if matched:
                if model.query:
                    return model.query, model_path or filename
                if model_path and Path(model_path).exists():
                    return read_model_sql(Path(model_path)), model_path

    try:
        reference_path = _resolve_path(project_root, models_dir, filename)
        if reference_path.exists():
            return read_model_sql(reference_path), str(reference_path)
    except Exception:
        pass

    return None, filename


def _extract_contract_config(config: FitnessFunctionsConfig) -> dict:
    """Extract schema contract parity groups from config or legacy JSON file."""
    column_parity_groups: list[dict] = []
    dimension_parity_groups: list[dict] = []

    cfg_contracts = getattr(config.checks, "schema_contracts", None)
    if cfg_contracts:
        if hasattr(cfg_contracts, "column_parity_groups") and cfg_contracts.column_parity_groups:
            column_parity_groups.extend(
                [g.model_dump() for g in cfg_contracts.column_parity_groups]
            )
        if hasattr(cfg_contracts, "dimension_parity_groups") and cfg_contracts.dimension_parity_groups:
            dimension_parity_groups.extend(
                [g.model_dump() for g in cfg_contracts.dimension_parity_groups]
            )

    if config.contract_groups:
        if config.contract_groups.column_parity_groups:
            column_parity_groups.extend(
                [g.model_dump() for g in config.contract_groups.column_parity_groups]
            )
        if config.contract_groups.dimension_parity_groups:
            dimension_parity_groups.extend(
                [g.model_dump() for g in config.contract_groups.dimension_parity_groups]
            )

    if column_parity_groups or dimension_parity_groups:
        return {
            "column_parity_groups": column_parity_groups,
            "dimension_parity_groups": dimension_parity_groups,
        }

    # Fallback to legacy JSON file
    if config.contract_groups_path:
        try:
            contract_path = resolve_project_path(config, config.contract_groups_path)
            if contract_path.exists():
                return json.loads(contract_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    return {}


def _schema_contract_errors(
    project_root: Path,
    contract_config: dict,
    models: dict[str, ModelRepresentation] | None = None,
) -> list[str]:
    errors: list[str] = []
    for group in contract_config.get("column_parity_groups", []):
        models_dir = group.get("models_dir", "")
        ref_name = group["reference"]
        ref_sql, _ = _get_model_sql_and_path(project_root, models_dir, ref_name, models)
        if ref_sql is None:
            errors.append(f"{Path(ref_name).name} not found")
            continue

        exclude = set(group.get("exclude_columns", []))
        ref_substitutions = group.get("reference_substitutions", {})
        reference_cols = normalize_columns(
            extract_final_select_columns(ref_sql),
            substitutions=ref_substitutions,
            exclude=exclude,
        )

        for member in group.get("members", []):
            member_file = member["file"] if isinstance(member, dict) else str(member)
            substitutions = member.get("substitutions", {}) if isinstance(member, dict) else {}
            member_sql, _ = _get_model_sql_and_path(
                project_root, models_dir, member_file, models
            )
            if member_sql is None:
                errors.append(f"{Path(member_file).name} not found")
                continue
            member_cols = normalize_columns(
                extract_final_select_columns(member_sql),
                substitutions=substitutions,
                exclude=exclude,
            )
            errors.extend(
                check_column_list_parity(
                    reference_cols,
                    member_cols,
                    group["reference"],
                    member_file,
                )
            )

    for group in contract_config.get("dimension_parity_groups", []):
        models_dir = group.get("models_dir", "")
        left_cfg = group["left"]
        right_cfg = group["right"]
        left_file = left_cfg["file"] if isinstance(left_cfg, dict) else str(left_cfg)
        right_file = right_cfg["file"] if isinstance(right_cfg, dict) else str(right_cfg)
        left_exclude = left_cfg.get("exclude_columns", []) if isinstance(left_cfg, dict) else []
        right_exclude = right_cfg.get("exclude_columns", []) if isinstance(right_cfg, dict) else []

        left_sql, _ = _get_model_sql_and_path(project_root, models_dir, left_file, models)
        right_sql, _ = _get_model_sql_and_path(project_root, models_dir, right_file, models)
        if left_sql is None or right_sql is None:
            continue

        left_dims = set(extract_final_select_columns(left_sql)) - set(left_exclude)
        right_dims = set(extract_final_select_columns(right_sql)) - set(right_exclude)
        errors.extend(
            check_dimension_set_parity(
                left_dims,
                right_dims,
                left_file,
                right_file,
            )
        )

    return errors


def collect_schema_contract_findings(
    models: dict[str, ModelRepresentation] | FitnessFunctionsConfig | None = None,
    config: FitnessFunctionsConfig | None = None,
) -> list[LintFinding]:
    if isinstance(models, FitnessFunctionsConfig) and config is None:
        config = models
        models = None

    if config is None:
        from tff.core.context import get_ff_config

        config = get_ff_config()

    project_root: Path = getattr(config, "_project_root", Path.cwd())
    contract_config = _extract_contract_config(config)
    if not contract_config:
        return []

    return [
        LintFinding(
            check="schema_contracts",
            severity="error",
            message=error.replace("\n", " — "),
        )
        for error in _schema_contract_errors(project_root, contract_config, models=models)
    ]
