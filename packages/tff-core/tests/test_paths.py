from tff.core.utils.paths import (
    get_layer_from_path,
    get_marts_domain_from_path,
    get_layer_and_domain,
)

LAYER_ORDER = ["1.staging", "2.refined", "marts"]


def test_get_layer_from_path_standard():
    path = "models/1.staging/my_model.sql"
    assert get_layer_from_path(path, layer_order=LAYER_ORDER) == "1.staging"


def test_get_layer_from_path_nested():
    path = "models/source_a/1.staging/my_model.sql"
    assert get_layer_from_path(path, layer_order=LAYER_ORDER) == "1.staging"


def test_get_layer_from_path_fallback():
    # If no segment in the path matches the config, fallback to the segment directly under models/
    path = "models/some_unknown_layer/my_model.sql"
    assert get_layer_from_path(path, layer_order=LAYER_ORDER) == "some_unknown_layer"


def test_get_layer_from_path_default_layer_order():
    path = "models/staging/my_model.sql"
    assert get_layer_from_path(path) == "staging"


def test_get_marts_domain_from_path_standard():
    path = "models/marts/finance/my_model.sql"
    assert get_marts_domain_from_path(path, "marts") == "finance"


def test_get_marts_domain_from_path_nested():
    path = "models/finance/marts/my_model.sql"
    assert get_marts_domain_from_path(path, "marts") == "finance"


def test_get_layer_and_domain_standard():
    path = "models/1.staging/finance/my_model.sql"
    assert get_layer_and_domain(path, layer_order=LAYER_ORDER) == ("1.staging", "finance")


def test_get_layer_and_domain_nested():
    path = "models/finance/1.staging/my_model.sql"
    assert get_layer_and_domain(path, layer_order=LAYER_ORDER) == ("1.staging", "finance")


def test_get_layer_and_domain_no_domain():
    path = "models/1.staging/my_model.sql"
    assert get_layer_and_domain(path, layer_order=LAYER_ORDER) == ("1.staging", "my_model")


def test_get_layer_and_domain_only_layer():
    path = "models/1.staging"
    assert get_layer_and_domain(path, layer_order=LAYER_ORDER) == ("1.staging", None)


def test_get_layer_and_domain_default_layer_order():
    path = "models/staging/finance/my_model.sql"
    assert get_layer_and_domain(path) == ("staging", "finance")


def test_model_path_relative():
    from pathlib import Path
    from tff.core.utils.paths import model_path_relative
    from tff.core.model import ModelRepresentation

    # Dict with path
    assert model_path_relative({"path": "models/marts/marketing/model.sql"}) == "models/marts/marketing/model.sql"
    assert model_path_relative({"_path": "/root/definitions/staging/stg.sqlx"}) == "definitions/staging/stg.sqlx"

    # String path
    assert model_path_relative("/root/workspace/models/core/dim_user.sql") == "models/core/dim_user.sql"

    # Path object
    assert model_path_relative(Path("/root/workspace/definitions/staging/stg.sqlx")) == "definitions/staging/stg.sqlx"

    # ModelRepresentation
    model = ModelRepresentation(name="dim_user", path="/root/models/core/dim_user.sql", dialect="postgres")
    assert model_path_relative(model) == "models/core/dim_user.sql"

    # Empty / None
    assert model_path_relative(None) is None
    assert model_path_relative({}) is None
