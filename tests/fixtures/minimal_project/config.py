from pathlib import Path

from sqlmesh.core.config import Config
from sqlmesh.utils.yaml import load as yaml_load

from sqlmesh_ff.loader import FitnessLoader

_settings = yaml_load(Path(__file__).parent / "settings.yaml")
config = Config.parse_obj(_settings).update_with({
    "loader": FitnessLoader,
    "loader_kwargs": {"fitness_functions_config": "fitness_functions.yaml"},
})
