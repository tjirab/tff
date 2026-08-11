from tff.core.utils.paths import (
    get_layer_from_path,
    get_marts_domain_from_path,
    get_layer_and_domain,
)
from tff.core.config import FitnessFunctionsConfig
from tff.core.context import set_ff_config, clear_ff_config
import pytest


@pytest.fixture(autouse=True)
def setup_config():
    config = FitnessFunctionsConfig()
    config.layers.order = ["1.staging", "2.refined", "marts"]
    set_ff_config(config)
    yield
    clear_ff_config()


def test_get_layer_from_path_standard():
    path = "models/1.staging/my_model.sql"
    assert get_layer_from_path(path) == "1.staging"


def test_get_layer_from_path_nested():
    path = "models/source_a/1.staging/my_model.sql"
    assert get_layer_from_path(path) == "1.staging"


def test_get_layer_from_path_fallback():
    # If no segment in the path matches the config, fallback to the segment directly under models/
    path = "models/some_unknown_layer/my_model.sql"
    assert get_layer_from_path(path) == "some_unknown_layer"


def test_get_marts_domain_from_path_standard():
    path = "models/marts/finance/my_model.sql"
    assert get_marts_domain_from_path(path, "marts") == "finance"


def test_get_marts_domain_from_path_nested():
    path = "models/finance/marts/my_model.sql"
    assert get_marts_domain_from_path(path, "marts") == "finance"


def test_get_layer_and_domain_standard():
    path = "models/1.staging/finance/my_model.sql"
    assert get_layer_and_domain(path) == ("1.staging", "finance")


def test_get_layer_and_domain_nested():
    path = "models/finance/1.staging/my_model.sql"
    assert get_layer_and_domain(path) == ("1.staging", "finance")


def test_get_layer_and_domain_no_domain():
    path = "models/1.staging/my_model.sql"
    assert get_layer_and_domain(path) == ("1.staging", "my_model")


def test_get_layer_and_domain_only_layer():
    path = "models/1.staging"
    assert get_layer_and_domain(path) == ("1.staging", None)
