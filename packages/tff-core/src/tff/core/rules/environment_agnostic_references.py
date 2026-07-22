"""Rule to ban hardcoded environment or database/catalog references in queries."""

from __future__ import annotations

import re
from pathlib import Path
import sqlglot
import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.context import get_ff_config
from tff.core.utils.paths import get_layer_from_path


def clean_query_for_parsing(sql: str) -> str:
    # Remove Jinja comments
    sql = re.sub(r"\{#.*?#\}", "", sql, flags=re.DOTALL)
    # Replace Jinja statement blocks with space
    sql = re.sub(r"\{%.*?%\}", " ", sql, flags=re.DOTALL)
    # Replace Jinja expression blocks with dummy identifier
    sql = re.sub(r"\{\{.*?\}\}", " __jinja_var__ ", sql, flags=re.DOTALL)
    # Replace SQLMesh macros with dummy identifier
    sql = re.sub(r"@\w+\([^)]*\)", " __sqlmesh_macro__ ", sql)
    sql = re.sub(r"@\w+", " __sqlmesh_macro__ ", sql)
    return sql


class EnvironmentAgnosticReferences(Rule):
    """Ban hardcoded environment and database/catalog names in queries."""
    name = "environmentagnosticreferences"

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = get_ff_config().rules.environment_agnostic_references
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path)
        if not rule_config.should_run(layer):
            return None

        # Always parse the raw SQL file on disk if possible,
        # otherwise fall back to model.query.
        # This is because model.query in dbt could contain compiled code
        # which has dynamically injected environments that we don't want to flag.
        sql = None
        if model.path:
            path = Path(model.path)
            if path.exists():
                sql = path.read_text(encoding="utf-8")

        if sql is None:
            sql = model.query

        if sql is None:
            return None

        try:
            # Strip SQLMesh MODEL block if present
            sql = re.sub(r"^MODEL\s*\(.*?\)\s*;", "", sql, flags=re.DOTALL | re.IGNORECASE).strip()
            # Clean Jinja and SQLMesh macro templates
            sql_clean = clean_query_for_parsing(sql)
            parsed = sqlglot.parse_one(sql_clean, read=model.dialect)
        except Exception:
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
