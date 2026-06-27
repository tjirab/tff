"""SQLMesh adapter for Transformation Fitness Functions (tff)."""

from tff.sqlmesh.loader import FitnessLoader
from tff.sqlmesh.runner import run_all_checks

__all__ = [
    "FitnessLoader",
    "run_all_checks",
]
