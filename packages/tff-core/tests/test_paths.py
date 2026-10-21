from pathlib import Path

import pytest

from conftest import _make_model
from tff.core.utils.paths import (
    get_layer_and_domain,
    get_layer_from_path,
    get_marts_domain_from_path,
    model_path_relative,
)

LAYER_ORDER = ["1.staging", "2.refined", "marts"]


@pytest.mark.parametrize(
    "path,layer_order,expected",
    [
        ("models/1.staging/my_model.sql", LAYER_ORDER, "1.staging"),
        ("models/source_a/1.staging/my_model.sql", LAYER_ORDER, "1.staging"),
        # If no segment in the path matches the config, fallback to the segment directly under models/
        ("models/some_unknown_layer/my_model.sql", LAYER_ORDER, "some_unknown_layer"),
        ("models/staging/my_model.sql", None, "staging"),
    ],
)
def test_get_layer_from_path(path: str, layer_order: list[str] | None, expected: str):
    if layer_order is not None:
        assert get_layer_from_path(path, layer_order=layer_order) == expected
    else:
        assert get_layer_from_path(path) == expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("models/marts/finance/my_model.sql", "finance"),
        ("models/finance/marts/my_model.sql", "finance"),
    ],
)
def test_get_marts_domain_from_path(path: str, expected: str):
    assert get_marts_domain_from_path(path, "marts") == expected


@pytest.mark.parametrize(
    "path,layer_order,expected",
    [
        ("models/1.staging/finance/my_model.sql", LAYER_ORDER, ("1.staging", "finance")),
        ("models/finance/1.staging/my_model.sql", LAYER_ORDER, ("1.staging", "finance")),
        ("models/1.staging/my_model.sql", LAYER_ORDER, ("1.staging", "my_model")),
        ("models/1.staging", LAYER_ORDER, ("1.staging", None)),
        ("models/staging/finance/my_model.sql", None, ("staging", "finance")),
    ],
)
def test_get_layer_and_domain(
    path: str, layer_order: list[str] | None, expected: tuple[str | None, str | None]
):
    if layer_order is not None:
        assert get_layer_and_domain(path, layer_order=layer_order) == expected
    else:
        assert get_layer_and_domain(path) == expected


def test_model_path_relative():
    # Dict with path
    assert model_path_relative({"path": "models/marts/marketing/model.sql"}) == "models/marts/marketing/model.sql"
    assert model_path_relative({"_path": "/root/definitions/staging/stg.sqlx"}) == "definitions/staging/stg.sqlx"

    # String path
    assert model_path_relative("/root/workspace/models/core/dim_user.sql") == "models/core/dim_user.sql"

    # Path object
    assert model_path_relative(Path("/root/workspace/definitions/staging/stg.sqlx")) == "definitions/staging/stg.sqlx"

    # ModelRepresentation
    model = _make_model(name="dim_user", path="/root/models/core/dim_user.sql", dialect="postgres")
    assert model_path_relative(model) == "models/core/dim_user.sql"

    # Empty / None
    assert model_path_relative(None) is None
    assert model_path_relative({}) is None
