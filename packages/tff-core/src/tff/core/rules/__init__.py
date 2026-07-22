"""Fitness function rules exported by tff-core."""

from tff.core.rules.classification_macros import ClassificationMacros
from tff.core.rules.column_names import ColumnNames
from tff.core.rules.column_types import ColumnTypes
from tff.core.rules.filename_equals_modelname import FilenameEqualsModelname
from tff.core.rules.mart_naming import MartModelNamingConvention
from tff.core.rules.metadata import (
    NoMissingDescription,
    NoMissingGrain,
    NoMissingNotNull,
    NoMissingOwner,
    NoMissingUniqueValues,
)
from tff.core.rules.no_positional_group_by_or_order_by import (
    NoPositionalGroupByOrOrderBy,
)
from tff.core.rules.ban_select_star import BanSelectStar
from tff.core.rules.sql_complexity import SqlComplexity
from tff.core.rules.environment_agnostic_references import EnvironmentAgnosticReferences

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
    BanSelectStar,
    NoPositionalGroupByOrOrderBy,
    EnvironmentAgnosticReferences,
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
    "BanSelectStar",
    "NoPositionalGroupByOrOrderBy",
    "EnvironmentAgnosticReferences",
]
