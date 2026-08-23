import warnings

warnings.warn(
    "sqlmesh-ff has been deprecated in favor of tff-core[sqlmesh]. Please install tff-core[sqlmesh] and import tff.sqlmesh instead.",
    DeprecationWarning,
    stacklevel=2,
)

from tff.sqlmesh.loader import FitnessLoader  # noqa: F401, E402
