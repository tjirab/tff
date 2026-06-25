"""Cross-model schema contract parity checks."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmesh_ff.config import (
    FitnessFunctionsConfig,
    _ensure_under_root,
    resolve_project_path,
)
from sqlmesh_ff.report import LintFinding
from sqlmesh_ff.utils.schema_contract_utils import (
    check_column_list_parity,
    check_dimension_set_parity,
    extract_final_select_columns,
    normalize_columns,
    read_model_sql,
)


def _resolve_path(project_root: Path, models_dir: str, filename: str) -> Path:
    return _ensure_under_root(project_root / models_dir / filename, project_root)


def _schema_contract_errors(project_root: Path, contract_config: dict) -> list[str]:
    errors: list[str] = []
    for group in contract_config.get("column_parity_groups", []):
        models_dir = group["models_dir"]
        reference_path = _resolve_path(project_root, models_dir, group["reference"])
        if not reference_path.exists():
            errors.append(f"{reference_path.name} not found")
            continue

        exclude = set(group.get("exclude_columns", []))
        ref_substitutions = group.get("reference_substitutions", {})
        reference_cols = normalize_columns(
            extract_final_select_columns(read_model_sql(reference_path)),
            substitutions=ref_substitutions,
            exclude=exclude,
        )

        for member in group["members"]:
            member_path = _resolve_path(project_root, models_dir, member["file"])
            if not member_path.exists():
                errors.append(f"{member_path.name} not found")
                continue
            member_cols = normalize_columns(
                extract_final_select_columns(read_model_sql(member_path)),
                substitutions=member.get("substitutions", {}),
                exclude=exclude,
            )
            errors.extend(
                check_column_list_parity(
                    reference_cols,
                    member_cols,
                    group["reference"],
                    member["file"],
                )
            )

    for group in contract_config.get("dimension_parity_groups", []):
        models_dir = group["models_dir"]
        left_cfg = group["left"]
        right_cfg = group["right"]
        left_path = _resolve_path(project_root, models_dir, left_cfg["file"])
        right_path = _resolve_path(project_root, models_dir, right_cfg["file"])
        if not left_path.exists() or not right_path.exists():
            continue

        left_dims = set(extract_final_select_columns(read_model_sql(left_path))) - set(
            left_cfg.get("exclude_columns", [])
        )
        right_dims = set(extract_final_select_columns(read_model_sql(right_path))) - set(
            right_cfg.get("exclude_columns", [])
        )
        errors.extend(
            check_dimension_set_parity(
                left_dims,
                right_dims,
                left_cfg["file"],
                right_cfg["file"],
            )
        )

    return errors


def collect_schema_contract_findings(
    config: FitnessFunctionsConfig,
) -> list[LintFinding]:
    project_root: Path = getattr(config, "_project_root", Path.cwd())
    contract_path = resolve_project_path(config, config.contract_groups_path)
    if not contract_path.exists():
        return []

    contract_config = json.loads(contract_path.read_text(encoding="utf-8"))
    return [
        LintFinding(
            check="schema_contracts",
            severity="error",
            message=error.replace("\n", " — "),
        )
        for error in _schema_contract_errors(project_root, contract_config)
    ]
