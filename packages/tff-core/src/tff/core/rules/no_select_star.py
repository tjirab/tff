"""Rule to ban SELECT * expressions."""

from __future__ import annotations

from pathlib import Path
import sqlglot
import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config
from tff.core.utils.paths import get_layer_from_path


class NoSelectStar(Rule):
    """Ban SELECT * expressions in configured layers."""
    name = "noselectstar"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.no_select_star
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        path = Path(model.path)
        if not path.exists():
            return None

        try:
            sql = path.read_text(encoding="utf-8")
            # Strip SQLMesh MODEL block if present
            import re
            sql = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
            parsed = sqlglot.parse_one(sql, read=model.dialect)
        except Exception:
            return None

        violations = []
        for star in parsed.find_all(exp.Star):
            violations.append(
                "SELECT * is prohibited. Explicitly name your columns to reduce coupling."
            )

        if violations:
            return self.violation(violations)
        return None
