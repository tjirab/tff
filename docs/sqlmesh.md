# Using TFF with SQLMesh

TFF integrates with [SQLMesh](https://sqlmesh.com) using the `tff-sqlmesh` package. It runs fitness checks in two ways:
1. **Directly inside SQLMesh**: Automatically hooks into SQLMesh's native `sqlmesh lint` CLI via a custom project loader.
2. **Via the standalone CLI**: Run checks independently with the `tff lint` command.

---

## Installation

Install the SQLMesh adapter:

```bash
# With uv:
uv add tff-sqlmesh

# Or pip:
pip install tff-sqlmesh
```

---

## Quick Start

1. Add `fitness_functions.yaml` to your SQLMesh project root.
2. Add a `config.py` loader bootstrap in your project root (see below).
3. Execute the linter:

```bash
# Via SQLMesh CLI (runs classification/metadata/naming/select-star rules):
sqlmesh lint

# Via TFF standalone CLI (runs rules + architectural checks like layers & graphs):
tff lint
```

---

## Where Configuration Lives

| File | Role | You edit this? |
|------|------|----------------|
| `fitness_functions.yaml` | Toggles, thresholds, and parameters for all checks and rules. | **Yes** — main fitness config. |
| `settings.yaml` | SQLMesh specific settings, including active linter rules. | **Yes** — normal SQLMesh config. |
| `config.py` | Python file in project root that imports `FitnessLoader` to register the adapter. | **Rarely** — simple ~10 lines of boilerplate. |
| `linter_contract_groups.json` | Parity group definitions for schema contracts. | **Yes** — project specific schema data. |
| `linter_exclusions.json` | Exclusions for layer boundaries or custom exceptions. | **Yes** — project specific exclusions. |

---

## Loader Bootstrap (`config.py`)

SQLMesh requires configuration loader classes to be defined in Python code. Since SQLMesh rejects having both a `config.py` and `config.yaml` in the same directory, we use `settings.yaml` to store SQLMesh settings, and load them in `config.py` while registering the `FitnessLoader` class:

```python
from pathlib import Path
from sqlmesh.core.config import Config
from sqlmesh.utils.yaml import load as yaml_load
from tff.sqlmesh.loader import FitnessLoader

_settings = yaml_load(Path(__file__).parent / "settings.yaml")
config = Config.parse_obj(_settings).update_with({
    "loader": FitnessLoader,
    "loader_kwargs": {"fitness_functions_config": "fitness_functions.yaml"},
})
```

---

## Rule Name Mapping

When using SQLMesh's native linter (`sqlmesh lint`), rules are enabled under `linter.rules` in `settings.yaml` using their lowercase class names:

| Config Key in `fitness_functions.yaml` | SQLMesh Rule Name | Class Name |
|----------------------------------------|-------------------|------------|
| `classification_macros` | `classificationmacros` | `ClassificationMacros` |
| `sql_complexity` | `sqlcomplexity` | `SqlComplexity` |
| `mart_naming` | `martmodelnamingconvention` | `MartModelNamingConvention` |
| `column_names` | `columnnames` | `ColumnNames` |
| `column_types` | `columntypes` | `ColumnTypes` |
| `metadata.owner` | `nomissingowner` | `NoMissingOwner` |
| `metadata.description` | `nomissingdescription` | `NoMissingDescription` |
| `metadata.grain` | `nomissinggrain` | `NoMissingGrain` |
| `filename_equals_modelname` | `filenameequalsmodelname` | `FilenameEqualsModelname` |
| `ban_select_star` | `banselectstar` | `BanSelectStar` |
| `no_positional_group_by_or_order_by` | `nopositionalgroupbyororderby` | `NoPositionalGroupByOrOrderBy` |
| `environment_agnostic_references` | `environmentagnosticreferences` | `EnvironmentAgnosticReferences` |

---

## CLI Options

### `tff lint`

```bash
tff lint [--project PATH] [--config PATH] [--provider PROVIDER] [--checks CHECK,...] [--fail-level error|warning] [--group-by connascence|model]
```

* **`--project`**: Path to your project root (default: current directory).
* **`--config`**: Path to `fitness_functions.yaml` (default: `fitness_functions.yaml`).
* **`--provider`**: The pipeline engine provider: `auto`, `dbt`, or `sqlmesh` (default: `auto`).
* **`--checks`**: Comma-separated list of checks (e.g., `layer_integrity,custom_exclusions`).
* **`--fail-level`**: Exit non-zero when findings at or above this severity exist (`error` or `warning`, default: `error`).
* **`--group-by`**: Changes report grouping format (`connascence` or `model`, default: `model`).

### `tff health`

```bash
tff health [--project PATH] [--config PATH] [--provider PROVIDER] [--fail-under SCORE] [--scope PATH_PREFIX ...] [--group-by connascence|domain]
```

* **`--project`**: Path to your project root (default: current directory).
* **`--config`**: Path to `fitness_functions.yaml` (default: `fitness_functions.yaml`).
* **`--provider`**: The pipeline engine provider: `auto`, `dbt`, or `sqlmesh` (default: `auto`).
* **`--fail-under`**: Exit non-zero when the overall health score (0–100) is below this threshold (default: `0.0`).
* **`--scope`**: Restrict the report to models whose path starts with one or more given prefixes. Multiple prefixes are supported. Examples:
  ```bash
  tff health --scope models/sources
  tff health --scope models/marts/marketing
  tff health --scope models/marts/marketing models/marts/finance
  ```
* **`--group-by`**: Controls the grouping of the detailed health breakdown:
  * `connascence` *(default)* — groups checks by connascence category (CoN, CoT, CoP, …).
  * `domain` — groups by path segment under `models/` (e.g. `models/sources`, `models/marts/marketing`), making it easy to see which domain is the weakest.
  ```bash
  tff health --group-by domain
  tff health --scope models/marts --group-by domain
  ```

