"""Rule to disallow inline subqueries in models."""

from __future__ import annotations

import sqlglot.expressions as exp

from tff.core.model import ModelRepresentation
from tff.core.rules.base import Rule, RuleViolation
from tff.core.utils.paths import get_layer_from_path


def find_subqueries(expression: exp.Expression) -> list[exp.Expression]:
    """Find all inline subqueries within an expression tree.

    Identifies:
    - Scalar subqueries in SELECT clauses: SELECT (SELECT ...)
    - Derived tables / inline subqueries in FROM or JOIN clauses: FROM (SELECT ...)
    - Predicate subqueries in WHERE or HAVING clauses: WHERE x IN (SELECT ...), WHERE x > (SELECT ...)
    - Existential subqueries: WHERE EXISTS (SELECT ...)
    - Subqueries nested within CTE bodies: WITH cte AS (SELECT * FROM (SELECT ...))

    Excludes:
    - Common Table Expressions (CTEs) at the top-level or within WITH blocks
    - Top-level or CTE-level set operation branches: (SELECT 1) UNION (SELECT 2)
    - Top-level parenthesized queries: (SELECT 1)
    """
    subqueries: list[exp.Expression] = []

    # 1. exp.Exists is always an existential subquery
    for exists in expression.find_all(exp.Exists):
        subqueries.append(exists)

    # 2. exp.Subquery
    for sq in expression.find_all(exp.Subquery):
        parent = sq.parent
        # If sq is the root of the parsed AST, it's just parenthesized main query e.g. (SELECT 1)
        if parent is None:
            continue
        # If sq is directly the query body of a CTE: WITH cte AS ((SELECT 1))
        if isinstance(parent, exp.CTE) and parent.this is sq:
            continue
        # If sq is an arm of a top-level or CTE-level SetOp: e.g. (SELECT 1) UNION (SELECT 2)
        if isinstance(parent, (exp.Union, exp.Intersect, exp.Except)):
            curr: exp.Expression = parent
            while curr.parent and isinstance(curr.parent, (exp.Union, exp.Intersect, exp.Except)):
                curr = curr.parent
            if curr.parent is None or isinstance(curr.parent, (exp.CTE, exp.With)):
                continue
        subqueries.append(sq)

    return subqueries


class NoSubqueries(Rule):
    """Ensure models use Common Table Expressions (CTEs) instead of inline subqueries."""

    name = "nosubqueries"
    aliases = ("nosubqueries", "ban_subqueries", "bansubqueries", "disallow_subqueries", "no_subquery")
    category = "Quality & Metadata (Non-Connascence)"
    is_fixable = False

    def check_model(self, model: ModelRepresentation) -> RuleViolation | None:
        rule_config = self.config.rules.no_subqueries
        if not rule_config.enabled:
            return None

        if model.is_symbolic:
            return None

        layer = get_layer_from_path(model.path, layer_order=self.config.layers.order)
        if not rule_config.should_run(layer):
            return None

        parsed = model.ast
        if parsed is None:
            return None

        subqueries = find_subqueries(parsed)
        if not subqueries:
            return None

        count = len(subqueries)
        suffix = "y" if count == 1 else "ies"
        return self.violation(
            [f"{count} inline subquer{suffix} found. Subqueries are prohibited; refactor into CTEs or upstream models."]
        )
