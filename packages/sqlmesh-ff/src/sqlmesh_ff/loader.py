import warnings

warnings.warn(
    "sqlmesh-ff has been renamed to tff-sqlmesh. Please install and import tff-sqlmesh instead.",
    DeprecationWarning,
    stacklevel=2,
)

from tff.sqlmesh.loader import FitnessLoader  # noqa: F401, E402
