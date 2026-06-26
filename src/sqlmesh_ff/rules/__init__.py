"""SQLMesh linter rules shipped by sqlmesh-ff."""

from sqlmesh_ff.rules.classification_macros import ClassificationMacros
from sqlmesh_ff.rules.column_names import ColumnNames
from sqlmesh_ff.rules.column_types import ColumnTypes
from sqlmesh_ff.rules.filename_equals_modelname import FilenameEqualsModelname
from sqlmesh_ff.rules.mart_naming import MartModelNamingConvention
from sqlmesh_ff.rules.metadata import (
    NoMissingDescription,
    NoMissingGrain,
    NoMissingNotNull,
    NoMissingOwner,
    NoMissingUniqueValues,
)
from sqlmesh_ff.rules.no_select_star import NoSelectStar
from sqlmesh_ff.rules.sql_complexity import SqlComplexity

ALL_RULES = [
    ClassificationMacros,
    SqlComplexity,
    MartModelNamingConvention,
    ColumnNames,
    ColumnTypes,
    NoMissingOwner,
    NoMissingDescription,
    NoMissingGrain,
    NoMissingNotNull,
    NoMissingUniqueValues,
    FilenameEqualsModelname,
    NoSelectStar,
]

__all__ = [
    "ALL_RULES",
    "ClassificationMacros",
    "SqlComplexity",
    "MartModelNamingConvention",
    "ColumnNames",
    "ColumnTypes",
    "NoMissingOwner",
    "NoMissingDescription",
    "NoMissingGrain",
    "NoMissingNotNull",
    "NoMissingUniqueValues",
    "FilenameEqualsModelname",
    "NoSelectStar",
]
