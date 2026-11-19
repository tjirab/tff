import pytest

from conftest import _make_column, _make_model
from tff.core.config import FitnessFunctionsConfig
from tff.core.rules.metadata import (
    NoMissingColumnMetadata,
    NoMissingDescription,
    NoMissingGrain,
    NoMissingNotNull,
    NoMissingOwner,
    NoMissingTableMetadata,
    NoMissingUniqueValues,
)


def test_no_missing_not_null_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.not_null = True

    rule = NoMissingNotNull(config=config)

    # Model with no audits
    model = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with not_null audit
    model_with_audit = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[("not_null", {})],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_audit) is None

    # Model with rule disabled in config
    config.rules.metadata.not_null = False
    assert rule.check_model(model) is None


def test_no_missing_unique_values_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.unique_values = True

    rule = NoMissingUniqueValues(config=config)

    # Model with no audits
    model = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with unique_values audit
    model_with_audit = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[("unique_values", {})],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_audit) is None

    # Model with rule disabled in config
    config.rules.metadata.unique_values = False
    assert rule.check_model(model) is None


def test_no_missing_owner_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.owner = True

    rule = NoMissingOwner(config=config)

    # Model with no owner
    model = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with owner
    model_with_owner = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        owner="data-team",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_owner) is None

    # Disabled
    config.rules.metadata.owner = False
    assert rule.check_model(model) is None


def test_no_missing_description_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.description = True

    rule = NoMissingDescription(config=config)

    # Model with no description
    model = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with description
    model_with_desc = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        description="A great model",
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_desc) is None

    # Disabled
    config.rules.metadata.description = False
    assert rule.check_model(model) is None


def test_no_missing_grain_rule():
    config = FitnessFunctionsConfig()
    config.rules.metadata.grain = True

    rule = NoMissingGrain(config=config)

    # Model with no grain
    model = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        grains=[],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model) is not None

    # Model with grain
    model_with_grain = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        grains=["user_id"],
        is_symbolic=False,
        is_external=False,
    )
    assert rule.check_model(model_with_grain) is None

    # Disabled
    config.rules.metadata.grain = False
    assert rule.check_model(model) is None


def test_rules_skip_symbolic_and_external_models():
    config = FitnessFunctionsConfig()
    config.rules.metadata.owner = True
    config.rules.metadata.description = True
    config.rules.metadata.grain = True
    config.rules.metadata.not_null = True
    config.rules.metadata.unique_values = True
    config.rules.metadata.table = {"priority": True}
    config.rules.metadata.column = {"tag": ["pii", "not_pii"]}

    rules = [
        NoMissingOwner(config=config),
        NoMissingDescription(config=config),
        NoMissingGrain(config=config),
        NoMissingNotNull(config=config),
        NoMissingUniqueValues(config=config),
        NoMissingTableMetadata(config=config),
        NoMissingColumnMetadata(config=config),
    ]

    # Symbolic model
    symbolic_model = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=True,
        is_external=False,
    )
    for rule in rules:
        assert rule.check_model(symbolic_model) is None

    # External model
    external_model = _make_model(
        name="test_model",
        path="models/marts/test_model.sql",
        dialect="bigquery",
        audits=[],
        is_symbolic=False,
        is_external=True,
    )
    for rule in rules:
        assert rule.check_model(external_model) is None


@pytest.mark.parametrize(
    ("meta", "tags", "table_config", "expect_violation", "expected_msg_fragment"),
    [
        ({}, [], {"priority": True}, True, "missing required table metadata 'priority'"),
        ({"priority": ""}, [], {"priority": True}, True, "missing required table metadata 'priority'"),
        ({"priority": "high"}, [], {"priority": True}, False, None),
        ({"Priority": "medium"}, [], {"priority": True}, False, None),  # case-insensitive
        ({}, ["priority:high"], {"priority": True}, False, None),  # tag prefix
        ({}, ["priority=p1"], {"priority": True}, False, None),  # tag prefix with equals
        ({"priority": "invalid"}, [], {"priority": ["high", "medium", "low"]}, True, "has invalid value 'invalid'"),
        ({"priority": "high"}, [], {"priority": ["high", "medium", "low"]}, False, None),
        ({"priority": "invalid"}, [], {"priority": {"pattern": r"^p[0-3]$"}}, True, "does not match required pattern"),
        ({"priority": "p1"}, [], {"priority": {"pattern": r"^p[0-3]$"}}, False, None),
        ({}, ["finance"], {"tag": ["finance", "marketing"]}, False, None),
        ({}, ["other"], {"tag": ["finance", "marketing"]}, True, "missing required tag from"),
        ({}, [], {"tag": {"required": True}}, True, "missing required table metadata 'tag'"),
        ({}, [], {"priority": {"required": False, "allowed_values": ["high"]}}, False, None),
        ({}, [], {}, False, None),
    ],
)
def test_no_missing_table_metadata_rule(meta, tags, table_config, expect_violation, expected_msg_fragment):
    config = FitnessFunctionsConfig()
    config.rules.metadata.enabled = True
    config.rules.metadata.table = table_config

    rule = NoMissingTableMetadata(config=config)
    model = _make_model(
        name="customers",
        path="models/marts/customers.sql",
        meta=meta,
        tags=tags,
    )

    result = rule.check_model(model)
    if expect_violation:
        assert result is not None
        assert expected_msg_fragment in str(result.violation_msg)
    else:
        assert result is None


@pytest.mark.parametrize(
    ("columns", "column_config", "expect_violation", "expected_msg_fragment"),
    [
        # Scenario: columns should be tagged either 'pii' or 'not_pii'
        (
            {
                "id": _make_column(name="id", tags=["not_pii"]),
                "email": _make_column(name="email", tags=["pii"]),
            },
            {"tag": ["pii", "not_pii"]},
            False,
            None,
        ),
        (
            {
                "id": _make_column(name="id", tags=["not_pii"]),
                "email": _make_column(name="email", tags=[]),
            },
            {"tag": ["pii", "not_pii"]},
            True,
            "Column 'email' in model 'customers' is missing required tag from: ['pii', 'not_pii']",
        ),
        (
            {
                "id": _make_column(name="id", tags=["not_pii"]),
                "email": _make_column(name="email", tags=["unknown_tag"]),
            },
            {"tag": ["pii", "not_pii"]},
            True,
            "Column 'email' in model 'customers' is missing required tag from: ['pii', 'not_pii']",
        ),
        # Required tag without allowed_values
        (
            {"id": _make_column(name="id", tags=[])},
            {"tag": {"required": True}},
            True,
            "Column 'id' in model 'customers' is missing required tags.",
        ),
        # Custom column metadata attribute
        (
            {"email": _make_column(name="email", meta={"classification": "confidential"})},
            {"classification": ["confidential", "public"]},
            False,
            None,
        ),
        (
            {"email": _make_column(name="email", meta={"classification": "secret"})},
            {"classification": ["confidential", "public"]},
            True,
            "metadata 'classification' has invalid value 'secret'",
        ),
        (
            {"email": _make_column(name="email", meta={})},
            {"classification": {"required": True}},
            True,
            "is missing required metadata 'classification'",
        ),
        # Attribute resolved from tag
        (
            {"email": _make_column(name="email", tags=["classification:confidential"])},
            {"classification": ["confidential", "public"]},
            False,
            None,
        ),
        # Regex pattern constraint on column attribute
        (
            {"email": _make_column(name="email", meta={"level": "L2"})},
            {"level": {"pattern": r"^L[1-5]$"}},
            False,
            None,
        ),
        (
            {"email": _make_column(name="email", meta={"level": "invalid"})},
            {"level": {"pattern": r"^L[1-5]$"}},
            True,
            "does not match required pattern",
        ),
        # Scoped to column_pattern
        (
            {
                "user_id": _make_column(name="user_id", tags=[]),
                "user_secret": _make_column(name="user_secret", tags=["pii"]),
            },
            {"tag": {"allowed_values": ["pii", "not_pii"], "column_pattern": r".*_secret$"}},
            False,
            None,
        ),
        # Skip columns
        (
            {"meta_col": _make_column(name="meta_col", tags=[])},
            {"tag": {"allowed_values": ["pii"], "skip_columns": ["meta_col"]}},
            False,
            None,
        ),
        # Case-insensitive column meta key
        (
            {"email": _make_column(name="email", meta={"Classification": "confidential"})},
            {"classification": ["confidential"]},
            False,
            None,
        ),
        # Exact tag match for column attr name
        (
            {"email": _make_column(name="email", tags=["pii"])},
            {"pii": {"required": True}},
            False,
            None,
        ),
        # Column tag with = prefix
        (
            {"email": _make_column(name="email", tags=["classification=confidential"])},
            {"classification": ["confidential"]},
            False,
            None,
        ),
        # Optional column attribute with None value
        (
            {"email": _make_column(name="email", meta={})},
            {"classification": {"required": False, "allowed_values": ["confidential"]}},
            False,
            None,
        ),
        # Empty columns or no column config
        ({}, {"tag": ["pii"]}, False, None),
    ],
)
def test_no_missing_column_metadata_rule(columns, column_config, expect_violation, expected_msg_fragment):
    config = FitnessFunctionsConfig()
    config.rules.metadata.enabled = True
    config.rules.metadata.column = column_config

    rule = NoMissingColumnMetadata(config=config)
    model = _make_model(
        name="customers",
        path="models/marts/customers.sql",
        columns=columns,
    )

    result = rule.check_model(model)
    if expect_violation:
        assert result is not None
        assert expected_msg_fragment in str(result.violation_msg)
    else:
        assert result is None


def test_metadata_rules_respect_skip_layers() -> None:
    config = FitnessFunctionsConfig()
    config.rules.metadata.enabled = True
    config.rules.metadata.skip_layers = ["marts"]
    config.rules.metadata.table = {"priority": True}
    config.rules.metadata.column = {"tag": ["pii"]}

    table_rule = NoMissingTableMetadata(config=config)
    col_rule = NoMissingColumnMetadata(config=config)

    model = _make_model(
        name="customers",
        path="models/marts/customers.sql",
        columns={"id": _make_column(name="id", tags=[])},
    )
    assert table_rule.check_model(model) is None
    assert col_rule.check_model(model) is None


def test_sqlmesh_runner_resolves_custom_metadata_checks() -> None:
    from tff.sqlmesh.runner import get_executed_checks

    config = FitnessFunctionsConfig()
    config.rules.metadata.enabled = True
    config.rules.metadata.table = {"priority": True}
    config.rules.metadata.column = {"tag": ["pii"]}

    executed = get_executed_checks(config)
    assert "nomissingtablemetadata" in executed
    assert "nomissingcolumnmetadata" in executed

