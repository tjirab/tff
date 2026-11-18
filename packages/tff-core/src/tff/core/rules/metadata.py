"""Metadata fitness rules — owner, description, grain, table metadata, and column metadata."""

from __future__ import annotations

import re
from typing import Any

from tff.core.config import MetadataAttributeRequirement, _normalize_metadata_attributes
from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.utils.paths import get_layer_from_path


class NoMissingOwner(Rule):
    """Model owner should always be specified."""
    name = "nomissingowner"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.metadata
        if not rule_config.owner:
            return None

        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation() if not model.owner else None
        )


class NoMissingDescription(Rule):
    """Model description should always be specified."""
    name = "nomissingdescription"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.metadata
        if not rule_config.description:
            return None

        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if not model.description
            else None
        )


class NoMissingGrain(Rule):
    """Model grains should always be specified."""
    name = "nomissinggrain"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.metadata
        if not rule_config.grain:
            return None

        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        return (
            self.violation()
            if not model.grains
            else None
        )


class NoMissingNotNull(Rule):
    """Model must have a not_null audit specified."""
    name = "nomissingnotnull"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.metadata
        if not rule_config.not_null:
            return None
        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        has_not_null = any(name == "not_null" for name, _ in model.audits)
        return self.violation() if not has_not_null else None


class NoMissingUniqueValues(Rule):
    """Model must have a unique_values audit specified."""
    name = "nomissinguniquevalues"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.metadata
        if not rule_config.unique_values:
            return None
        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        has_unique_values = any(name == "unique_values" for name, _ in model.audits)
        return self.violation() if not has_unique_values else None


class NoMissingTableMetadata(Rule):
    """Required table metadata attributes and allowed values must be specified."""
    name = "nomissingtablemetadata"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.metadata
        if not rule_config.enabled or not rule_config.table:
            return None
        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        violations: list[str] = []
        for attr_name, raw_req in rule_config.table.items():
            req = (
                raw_req
                if isinstance(raw_req, MetadataAttributeRequirement)
                else _normalize_metadata_attributes({attr_name: raw_req})[attr_name]
            )
            val = self._resolve_table_attr(model, attr_name)

            if req.required:
                if val is None or val == "" or (isinstance(val, (list, dict)) and len(val) == 0):
                    violations.append(
                        f"Model '{model.name}' is missing required table metadata '{attr_name}'."
                    )
                    continue

            if val is None:
                continue

            if req.allowed_values is not None:
                if attr_name.lower() in ("tag", "tags") and isinstance(val, list):
                    allowed_norm = [str(av).lower() for av in req.allowed_values]
                    has_match = any(str(t).lower() in allowed_norm for t in val)
                    if not has_match:
                        violations.append(
                            f"Model '{model.name}' is missing required tag from: {req.allowed_values}."
                        )
                else:
                    val_str = str(val).lower() if isinstance(val, (str, int, float, bool)) else val
                    allowed_norm = [
                        str(av).lower() if isinstance(av, (str, int, float, bool)) else av
                        for av in req.allowed_values
                    ]
                    if val_str not in allowed_norm:
                        violations.append(
                            f"Model '{model.name}' metadata '{attr_name}' has invalid value '{val}'. Expected one of: {req.allowed_values}."
                        )

            if req.pattern is not None:
                if not re.search(req.pattern, str(val)):
                    violations.append(
                        f"Model '{model.name}' metadata '{attr_name}' value '{val}' does not match required pattern '{req.pattern}'."
                    )

        if violations:
            return self.violation(violations)
        return None

    @staticmethod
    def _resolve_table_attr(model: ModelRepresentation, attr_name: str) -> Any:
        # Check model.meta direct key
        if model.meta:
            if attr_name in model.meta:
                return model.meta[attr_name]
            # Case-insensitive
            for k, v in model.meta.items():
                if k.lower() == attr_name.lower():
                    return v

        # Check tag/tags
        if attr_name.lower() in ("tag", "tags"):
            return model.tags or []

        # Check prefixed tags (e.g. priority:high)
        if model.tags:
            for t in model.tags:
                prefix = f"{attr_name.lower()}:"
                prefix_eq = f"{attr_name.lower()}="
                if t.lower().startswith(prefix):
                    return t[len(prefix):]
                if t.lower().startswith(prefix_eq):
                    return t[len(prefix_eq):]

        return None


class NoMissingColumnMetadata(Rule):
    """Required column metadata attributes and tags must be specified."""
    name = "nomissingcolumnmetadata"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.metadata
        if not rule_config.enabled or not rule_config.column:
            return None
        if model.is_external or model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        if not model.columns:
            return None

        violations: list[str] = []
        for attr_name, raw_req in rule_config.column.items():
            req = (
                raw_req
                if isinstance(raw_req, MetadataAttributeRequirement)
                else _normalize_metadata_attributes({attr_name: raw_req})[attr_name]
            )
            for col_name, col in model.columns.items():
                if req.skip_columns and (col_name in req.skip_columns or col.name in req.skip_columns):
                    continue
                if req.column_pattern and not re.search(req.column_pattern, col.name):
                    continue

                if attr_name.lower() in ("tag", "tags"):
                    col_tags = col.tags or []
                    if req.required and not col_tags and not req.allowed_values:
                        violations.append(
                            f"Column '{col.name}' in model '{model.name}' is missing required tags."
                        )
                        continue
                    if req.allowed_values is not None:
                        allowed_norm = [str(av).lower() for av in req.allowed_values]
                        has_match = any(str(t).lower() in allowed_norm for t in col_tags)
                        if not has_match:
                            violations.append(
                                f"Column '{col.name}' in model '{model.name}' is missing required tag from: {req.allowed_values}."
                            )
                else:
                    val = self._resolve_column_attr(col, attr_name)

                    if req.required:
                        if val is None or val == "":
                            violations.append(
                                f"Column '{col.name}' in model '{model.name}' is missing required metadata '{attr_name}'."
                            )
                            continue

                    if val is None:
                        continue

                    if req.allowed_values is not None:
                        val_str = str(val).lower() if isinstance(val, (str, int, float, bool)) else val
                        allowed_norm = [
                            str(av).lower() if isinstance(av, (str, int, float, bool)) else av
                            for av in req.allowed_values
                        ]
                        if val_str not in allowed_norm:
                            violations.append(
                                f"Column '{col.name}' in model '{model.name}' metadata '{attr_name}' has invalid value '{val}'. Expected one of: {req.allowed_values}."
                            )

                    if req.pattern is not None:
                        if not re.search(req.pattern, str(val)):
                            violations.append(
                                f"Column '{col.name}' in model '{model.name}' metadata '{attr_name}' value '{val}' does not match required pattern '{req.pattern}'."
                            )

        if violations:
            return self.violation(violations)
        return None

    @staticmethod
    def _resolve_column_attr(col: Any, attr_name: str) -> Any:
        col_meta = getattr(col, "meta", None) or {}
        if attr_name in col_meta:
            return col_meta[attr_name]
        for k, v in col_meta.items():
            if k.lower() == attr_name.lower():
                return v

        col_tags = getattr(col, "tags", None) or []
        for t in col_tags:
            if t.lower() == attr_name.lower():
                return t
            prefix = f"{attr_name.lower()}:"
            prefix_eq = f"{attr_name.lower()}="
            if t.lower().startswith(prefix):
                return t[len(prefix):]
            if t.lower().startswith(prefix_eq):
                return t[len(prefix_eq):]

        return None
