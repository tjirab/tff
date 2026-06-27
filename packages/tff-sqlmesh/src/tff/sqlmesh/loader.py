"""SQLMesh loader that wraps tff-core package rules and registers them."""

from __future__ import annotations

import os
import typing as t
from pathlib import Path

from sqlglot.helper import subclasses
from sqlmesh.core import constants as c
from sqlmesh.core.linter.definition import RuleSet
from sqlmesh.core.linter.rule import Rule as SqlMeshRule, RuleViolation as SqlMeshRuleViolation
from sqlmesh.core.model import Model as SqlMeshModel
from sqlmesh.core.loader import SqlMeshLoader
from sqlmesh.utils import UniqueKeyDict
from sqlmesh.utils.metaprogramming import import_python_file

from tff.core.config import load_fitness_config
from tff.core.context import set_ff_config
from tff.core.model import ModelRepresentation
from tff.core.rules import ALL_RULES as CORE_RULES


def map_sqlmesh_model(model: SqlMeshModel) -> ModelRepresentation:
    columns_to_types = {
        name: str(dtype)
        for name, dtype in (model.columns_to_types or {}).items()
    }
    
    audits = []
    if model.audits:
        for audit_name, audit_args in model.audits:
            audits.append((audit_name, audit_args or {}))

    if not model.dialect:
        raise ValueError(f"Model {model.name} does not have a SQL dialect configured.")

    return ModelRepresentation(
        name=str(model.name),
        path=str(model._path),
        dialect=model.dialect,
        is_symbolic=bool(model.kind.is_symbolic),
        is_external=bool(model.kind.name == "EXTERNAL"),
        columns_to_types=columns_to_types,
        depends_on={str(dep) for dep in model.depends_on},
        description=model.description,
        owner=model.owner,
        grains=[str(g) for g in (model.grains or [])],
        audits=audits,
    )


def wrap_core_rule(core_rule_cls) -> type[SqlMeshRule]:
    def check_model(self, model: SqlMeshModel) -> t.Optional[SqlMeshRuleViolation]:
        rep = map_sqlmesh_model(model)
        rule_instance = core_rule_cls()
        violation = rule_instance.check_model(rep)
        if violation:
            return self.violation(violation.violation_msg)
        return None

    cls_name = core_rule_cls.__name__
    attrs = {
        "check_model": check_model,
        "__doc__": core_rule_cls.__doc__,
    }
    return type(cls_name, (SqlMeshRule,), attrs)


class FitnessLoader(SqlMeshLoader):
    """Load core fitness rules adapted for SQLMesh, plus optional project-local rules."""

    def __init__(self, context, path: Path, **loader_kwargs: t.Any) -> None:
        super().__init__(context, path)
        config_path = loader_kwargs.get("fitness_functions_config", "fitness_functions.yaml")
        overrides = {
            key: value
            for key, value in loader_kwargs.items()
            if key != "fitness_functions_config"
        }
        ff_config = load_fitness_config(
            self.config_path,
            config_path=config_path,
            overrides=overrides or None,
        )
        set_ff_config(ff_config)
        self._ff_config = ff_config

    def _load_linting_rules(self) -> RuleSet:
        user_rules: UniqueKeyDict[str, type[SqlMeshRule]] = UniqueKeyDict("rules")

        # Dynamically wrap all tff-core rules to be SQLMesh-compatible
        for core_rule_cls in CORE_RULES:
            wrapped = wrap_core_rule(core_rule_cls)
            user_rules[wrapped.name] = wrapped

        for path in self._glob_paths(
            self.config_path / c.LINTER,
            ignore_patterns=self.config.ignore_patterns,
            extension=".py",
        ):
            if os.path.getsize(path):
                self._track_file(path)
                module = import_python_file(path, self.config_path)
                _rule_exclude: t.Set[t.Type[SqlMeshRule]] = {SqlMeshRule}  # type: ignore[type-abstract]
                module_rules = subclasses(module.__name__, SqlMeshRule, exclude=_rule_exclude)
                for user_rule in module_rules:
                    user_rules[user_rule.name] = user_rule

        return RuleSet(user_rules.values())
