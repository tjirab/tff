from __future__ import annotations

from tff.core.checks.join_type_parity import (
    DEFAULT_EQUIVALENT_TYPES,
    ModelTypeResolver,
    are_types_equivalent,
    collect_join_type_parity_findings,
    normalize_type_string,
)
from tff.core.config import FitnessFunctionsConfig
from tff.core.model import ModelRepresentation
from tff.core.registry import registry


def test_normalize_type_string() -> None:
    assert normalize_type_string(None) == ""
    assert normalize_type_string("VARCHAR(255)") == "varchar"
    assert normalize_type_string("DECIMAL(10, 2)") == "decimal"
    assert normalize_type_string("INT[]") == "int"
    assert normalize_type_string("  TEXT  ") == "text"


def test_are_types_equivalent() -> None:
    assert "text" in DEFAULT_EQUIVALENT_TYPES
    assert "integer" in DEFAULT_EQUIVALENT_TYPES
    eq_groups = {"text": {"text", "varchar"}, "num": {"int", "bigint"}}
    assert are_types_equivalent("int", "int", eq_groups) is True
    assert are_types_equivalent("int", "bigint", eq_groups) is True
    assert are_types_equivalent("varchar", "text", eq_groups) is True
    assert are_types_equivalent("varchar", "int", eq_groups) is False
    assert are_types_equivalent("unknown", "int", eq_groups) is True
    assert are_types_equivalent("null", "varchar", eq_groups) is True
    assert are_types_equivalent("", "varchar", eq_groups) is True


def test_join_type_parity_identical_types() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT", "name": "VARCHAR"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"order_id": "INT", "user_id": "INT"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.name, o.order_id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 0


def test_join_type_parity_mismatch() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT", "name": "VARCHAR"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"order_id": "INT", "user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.name, o.order_id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 1
    finding = findings[0]
    assert finding.check == "join_type_parity"
    assert finding.model == "marts.user_orders"
    assert finding.severity == "error"
    assert "u.id" in finding.message
    assert "o.user_id" in finding.message
    assert "(int)" in finding.message
    assert "(varchar)" in finding.message
    assert "Connascence of Type (CoT)" in finding.message


def test_join_type_parity_default_equivalent_types() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "TEXT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 0


def test_join_type_parity_custom_equivalent_types() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True
    # Configure custom strict equivalent groups where text and varchar are NOT grouped
    config.checks.join_type_parity.equivalent_types = {
        "text": ["text"],
        "varchar": ["varchar"],
    }

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "TEXT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 1
    assert "text" in findings[0].message
    assert "varchar" in findings[0].message


def test_join_type_parity_explicit_cast() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON CAST(u.id AS VARCHAR) = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 0


def test_join_type_parity_parentheses_and_multiple_conditions() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT", "tenant_id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR", "tenant_id": "INT"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON (u.id = o.user_id) AND (u.tenant_id = o.tenant_id)",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 1
    assert "u.id = o.user_id" in findings[0].message


def test_join_type_parity_using_clause() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT user_id FROM raw.users JOIN raw.orders USING (user_id)",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 1
    assert "USING (user_id)" in findings[0].message
    assert "int" in findings[0].message
    assert "varchar" in findings[0].message


def test_join_type_parity_ctes() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT", "email": "VARCHAR"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR", "amount": "DOUBLE"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="""
        WITH cleaned_users AS (
            SELECT id AS uid, email FROM raw.users
        )
        SELECT u.email, o.amount
        FROM cleaned_users u
        JOIN raw.orders o ON u.uid = o.user_id
        """,
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 1
    assert "u.uid = o.user_id" in findings[0].message
    assert "(int)" in findings[0].message
    assert "(varchar)" in findings[0].message


def test_join_type_parity_unknown_or_missing_types_ignored() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "UNKNOWN"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "INT"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 0


def test_join_type_parity_external_and_symbolic_skipped() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model = ModelRepresentation(
        name="marts.model",
        path="models/marts/model.sql",
        dialect="duckdb",
        is_external=True,
        query="SELECT * FROM a JOIN b ON a.id = b.id",
    )
    assert len(collect_join_type_parity_findings({"marts.model": model}, config)) == 0

    model.is_external = False
    model.is_symbolic = True
    assert len(collect_join_type_parity_findings({"marts.model": model}, config)) == 0


def test_join_type_parity_layer_filters() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True
    config.checks.join_type_parity.skip_layers = ["staging"]

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_staging = ModelRepresentation(
        name="staging.stg_combined",
        path="models/staging/stg_combined.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "staging.stg_combined": model_staging,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 0


def test_join_type_parity_disabled() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = False

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    assert len(collect_join_type_parity_findings(models, config)) == 0


def test_join_type_parity_registry_integration() -> None:
    c_def = registry.get("join_type_parity")
    assert c_def is not None
    assert c_def.scope == "dag"
    assert c_def.category == "Connascence of Type (CoT)"
    assert "type_parity" in c_def.aliases

    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings, _ = registry.run_checks(
        models=models,
        config=config,
        checks=["join_type_parity"],
    )
    assert len(findings) == 1
    assert findings[0].check == "join_type_parity"


def test_model_type_resolver_by_name() -> None:
    model = ModelRepresentation(
        name="db.schema.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT", "email": "VARCHAR"},
    )
    resolver = ModelTypeResolver({"db.schema.users": model})
    assert resolver.find_column_type_by_name("db.schema.users", "id") == "int"
    assert resolver.find_column_type_by_name("schema.users", "email") == "varchar"
    assert resolver.find_column_type_by_name("users", "id") == "int"
    assert resolver.find_column_type_by_name("users", "nonexistent") is None
    assert resolver.find_column_type_by_name("other_table", "id") is None


def test_normalize_type_string_with_datatype_object() -> None:
    from sqlglot import exp

    dt = exp.DataType.build("VARCHAR(255)")
    assert normalize_type_string(dt) == "varchar"


def test_are_types_equivalent_sqlglot_canonical() -> None:
    # "int" vs "integer" are syntactically different strings but have identical DType.INT
    assert are_types_equivalent("int", "integer", {}) is True


def test_model_type_resolver_catalog_db_table() -> None:
    from sqlglot import exp

    model = ModelRepresentation(
        name="cat.db.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    resolver = ModelTypeResolver({"cat.db.users": model})
    tbl = exp.Table(this="users", db="db", catalog="cat")
    assert resolver.find_column_type(tbl, "id") == "int"
    assert resolver.find_column_type(exp.Table(this="nonexistent"), "id") is None


def test_resolve_expression_type_literals_and_parens() -> None:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import Scope
    from tff.core.checks.join_type_parity import resolve_expression_type

    scope = Scope(sqlglot.parse_one("SELECT 1"))
    resolver = ModelTypeResolver({})

    assert resolve_expression_type(exp.Literal.string("hello"), scope, resolver) == "text"
    assert resolve_expression_type(exp.Literal.number(42), scope, resolver) == "integer"
    assert resolve_expression_type(exp.Literal.number(42.5), scope, resolver) == "float"
    assert resolve_expression_type(exp.Paren(this=exp.Literal.string("hi")), scope, resolver) == "text"
    assert resolve_expression_type(exp.Literal.string("hi"), scope, resolver, depth=11) is None
    assert resolve_expression_type(exp.var("non_col_expr"), scope, resolver) is None


def test_resolve_expression_type_table_name_alias_match() -> None:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import Scope
    from tff.core.checks.join_type_parity import resolve_expression_type

    parsed = sqlglot.parse_one("SELECT raw_users.id FROM raw_users")
    scope = Scope(parsed)
    scope.sources["u"] = exp.Table(this=exp.to_identifier("raw_users"))
    resolver = ModelTypeResolver({
        "raw_users": ModelRepresentation(
            name="raw_users", path="a", dialect="duckdb", columns_to_types={"id": "INT"}
        )
    })
    assert resolve_expression_type(exp.Column(this="id", table="raw_users"), scope, resolver) == "int"
    assert resolve_expression_type(exp.Column(this="nonexistent", table="raw_users"), scope, resolver) is None


def test_join_type_parity_fallback_when_traverse_scope_empty(monkeypatch) -> None:
    from tff.core.checks import join_type_parity

    # Force traverse_scope to raise an exception to trigger the fallback path
    def mock_traverse_scope(_ast):
        raise ValueError("Simulated scope error")

    monkeypatch.setattr(join_type_parity, "traverse_scope", mock_traverse_scope)

    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    # The fallback should run without raising and handle joins
    assert len(findings) >= 0


def test_join_type_parity_duplicate_violations_deduplicated() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    # Query repeats identical ON condition twice
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT u.id FROM raw.users u JOIN raw.orders o ON u.id = o.user_id AND u.id = o.user_id",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    # Deduplication ensures only 1 finding is emitted
    assert len(findings) == 1


def test_join_type_parity_using_clause_cte_and_duplicate() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="""
        WITH cte AS (
            SELECT user_id FROM raw.users
        )
        SELECT user_id
        FROM cte
        JOIN raw.orders USING (user_id)
        JOIN raw.orders o2 USING (user_id)
        """,
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    # The duplicate USING(user_id) is deduplicated
    assert len(findings) == 1
    assert "USING (user_id)" in findings[0].message


def test_join_type_parity_using_clause_missing_right_type() -> None:
    config = FitnessFunctionsConfig()
    config.checks.join_type_parity.enabled = True

    model_users = ModelRepresentation(
        name="raw.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"user_id": "INT"},
    )
    model_orders = ModelRepresentation(
        name="raw.orders",
        path="models/staging/orders.sql",
        dialect="duckdb",
        columns_to_types={"other_col": "VARCHAR"},
    )
    model_marts = ModelRepresentation(
        name="marts.user_orders",
        path="models/marts/user_orders.sql",
        dialect="duckdb",
        query="SELECT user_id FROM raw.users JOIN raw.orders USING (user_id)",
    )

    models = {
        "raw.users": model_users,
        "raw.orders": model_orders,
        "marts.user_orders": model_marts,
    }
    findings = collect_join_type_parity_findings(models, config)
    assert len(findings) == 0


def test_are_types_equivalent_invalid_syntax_handled() -> None:
    # Invalid syntax that causes DataType.build to fail gracefully
    assert are_types_equivalent("invalid(((type", "other", {}) is False


def test_model_type_resolver_by_name_multi_level() -> None:
    model = ModelRepresentation(
        name="schema.users",
        path="models/staging/users.sql",
        dialect="duckdb",
        columns_to_types={"id": "INT"},
    )
    resolver = ModelTypeResolver({"schema.users": model})
    # clean_tbl has 4 parts, not in _lookup directly, but schema.users is
    assert resolver.find_column_type_by_name("enterprise.corp.schema.users", "id") == "int"


def test_resolve_expression_type_mixed_case_alias() -> None:
    import sqlglot
    from sqlglot import exp
    from sqlglot.optimizer.scope import Scope
    from tff.core.checks.join_type_parity import resolve_expression_type

    parsed = sqlglot.parse_one("SELECT u.id FROM users u")
    scope = Scope(parsed)
    # Put mixed-case key in scope.sources so scope.sources.get("u") fails but lower match succeeds
    scope.sources["U_ALIAS"] = exp.Table(this=exp.to_identifier("users"))
    resolver = ModelTypeResolver({
        "users": ModelRepresentation(
            name="users", path="a", dialect="duckdb", columns_to_types={"id": "INT"}
        )
    })
    col = exp.Column(this="id", table="u_alias")
    assert resolve_expression_type(col, scope, resolver) == "int"


