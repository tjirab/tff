"""Rule to ban hardcoded environment or database/catalog references in queries."""

from __future__ import annotations

import re
import sqlglot
import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.utils.paths import get_layer_from_path


from tff.core.utils.jinja import clean_jinja_for_parsing


class EnvironmentAgnosticReferences(Rule):
    """Ban hardcoded environment and database/catalog names in queries."""
    name = "environmentagnosticreferences"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.environment_agnostic_references
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        # If raw_ast was already parsed, reuse it.
        # Otherwise, if model.raw_code is None and model.path was read for model.ast, reuse model.ast
        parsed = model._raw_ast
        if parsed is None:
            raw_sql = model.raw_code
            if raw_sql is None and model.expression is not None:
                # model.expression was parsed from disk or query
                parsed = model.expression
            else:
                sql = model.get_sql(prefer_file=True)
                if sql is None:
                    return None
                try:
                    # Strip SQLMesh MODEL block if present
                    sql = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
                    # Clean Jinja and SQLMesh macro templates
                    sql_clean = clean_jinja_for_parsing(sql, provider=model.provider)
                    parsed = sqlglot.parse_one(sql_clean, read=model.dialect)
                    model._raw_ast = parsed
                except Exception:
                    return None

        if parsed is None:
            return None

        banned_envs = []
        for env in rule_config.banned_environments:
            banned_envs.append(env.replace("_", " ").replace("-", " ").lower().split())

        def is_sublist(sub: list[str], large: list[str]) -> bool:
            if not sub:
                return False
            n, m = len(large), len(sub)
            for i in range(n - m + 1):
                if large[i:i+m] == sub:
                    return True
            return False

        violations = []

        for table in parsed.find_all(exp.Table):
            # A table reference consists of a list of identifiers in 'parts'.
            # The last part is the table name itself. The preceding parts are database/schema prefixes.
            if len(table.parts) > 1:
                prefix_parts = table.parts[:-1]
                for part in prefix_parts:
                    part_name = part.name
                    # Tokenize the part name by replacing separators with spaces
                    normalized = part_name.replace("_", " ").replace("-", " ").lower()
                    words = normalized.split()
                    for env_words in banned_envs:
                        if is_sublist(env_words, words):
                            table_sql = table.sql()
                            env_name = "-".join(env_words)
                            violations.append(
                                f"Table reference '{table_sql}' contains hardcoded environment/catalog prefix '{part_name}' matching banned environment '{env_name}'."
                            )
                            break

        if violations:
            return self.violation(violations)
        return None
