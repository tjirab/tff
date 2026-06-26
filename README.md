# sqlmesh-ff

Configurable fitness functions plugin for [SQLMesh](https://sqlmesh.com) projects.

Ships SQLMesh linter rules (classification macros, SQL complexity, metadata, naming) and architectural checks (layer integrity, custom exclusions, schema contracts, dependency graph) with a unified Rich lint report.

## Installation

```bash
# Install directly from GitHub:
uv add git+https://github.com/tjirab/sqlmesh-ff.git

# Or from a local checkout:
uv add ../sqlmesh-ff
```

## Quick start

1. Add `fitness_functions.yaml` to your SQLMesh project root (see [Configuration](#configuration)).
2. Add a small `config.py` bootstrap (see [Where configuration lives](#where-configuration-lives)) — SQLMesh requires the loader as a Python class and cannot load `config.py` and `config.yaml` in the same folder.
3. Run lint:

```bash
sqlmesh-ff lint
```

## Where configuration lives

There are three layers. Only the YAML/JSON files in your project are user-editable settings.

| Layer | File | Role | You edit this? |
|-------|------|------|----------------|
| Plugin defaults | `sqlmesh_ff/config.py` (installed package) | Pydantic schema and built-in defaults (e.g. `fan_out_warn: 15`) | No — library code, never overwritten |
| SQLMesh project | `settings.yaml` | Gateways, `linter.rules`, variables, CI/CD bot | Yes — normal SQLMesh config |
| Fitness functions | `fitness_functions.yaml` | Thresholds, rule toggles, column naming/type rules, paths to JSON data | Yes — main FF config |
| Loader bootstrap | `config.py` (project root) | Loads `settings.yaml` and registers `FitnessLoader` | Rarely — ~15 lines of wiring |
| Contract data | `linter_contract_groups.json`, `linter_exclusions.json` | Repo-specific schema parity and dependency exclusions | Yes — project data |

**Merge order for fitness settings:** plugin defaults → `fitness_functions.yaml` → optional `loader_kwargs` overrides in `config.py`. Your YAML always wins over plugin defaults. The project `config.py` does not hold fitness thresholds — it only points at `fitness_functions.yaml`.

**Why `config.py` exists:** SQLMesh accepts `loader: FitnessLoader` only as a Python class, not as a YAML string. Because SQLMesh rejects having both `config.py` and `config.yaml` in one folder, projects use `settings.yaml` (SQLMesh settings) plus `config.py` (loader registration).

Example bootstrap:

```python
from pathlib import Path

from sqlmesh.core.config import Config
from sqlmesh.utils.yaml import load as yaml_load
from sqlmesh_ff.loader import FitnessLoader

_settings = yaml_load(Path(__file__).parent / "settings.yaml")
config = Config.parse_obj(_settings).update_with({
    "loader": FitnessLoader,
    "loader_kwargs": {"fitness_functions_config": "fitness_functions.yaml"},
})
```

Enable individual SQLMesh rules in `settings.yaml` under `linter.rules` / `linter.warn_rules`.

## Configuration

Fitness function settings live in `fitness_functions.yaml` at the project root. Override the file path or individual keys via `loader_kwargs` in `config.py` (advanced — most projects only set `fitness_functions_config`).

### Example `fitness_functions.yaml`

```yaml
contract_groups_path: linter_contract_groups.json
exclusions_path: linter_exclusions.json

layers:
  order: [sources, derived, core, marts, export]

checks:
  layer_integrity: { enabled: true }
  custom_exclusions: { enabled: true }
  schema_contracts: { enabled: true }
  dependency_graph:
    enabled: true
    fan_out_warn: 15
    fan_out_fail: 25
    fan_in_warn: 10

rules:
  classification_macros:
    enabled: true
    skip_layers: [sources]
    columns:
      product_type: "@product_type\\b|@PRODUCT_TYPE\\b"
  sql_complexity:
    enabled: true
    thresholds:
      decision_points: [15, 25]
      cte_count: [8, 12]
      join_count: [8, 12]
      line_count: [250, 400]
  mart_naming:
    enabled: true
    layer_name: marts
    rule: prefix_with_subdirectory
  column_names:
    enabled: true
    replacements: {}
  column_types:
    enabled: true
    rules: []
    equivalent_types:
      text: [text, varchar]
  metadata:
    owner: true
    description: true
    grain: true
  filename_equals_modelname:
    enabled: true
```

### Project-specific JSON

Keep repo-specific contract and exclusion data in your project:

- `linter_contract_groups.json` — cross-model schema parity groups
- `linter_exclusions.json` — blocked dependency patterns and allowed exceptions

Reference their paths from `fitness_functions.yaml`. The plugin ships generic engines only; examples live in this README.

### Rule name mapping

SQLMesh uses lowercase class names in `linter.rules`:

| Config key | SQLMesh rule name |
|------------|-------------------|
| `classification_macros` | `classificationmacros` |
| `sql_complexity` | `sqlcomplexity` |
| `mart_naming` | `martmodelnamingconvention` |
| `column_names` | `columnnames` |
| `column_types` | `columntypes` |
| `metadata.owner` | `nomissingowner` |
| `metadata.description` | `nomissingdescription` |
| `metadata.grain` | `nomissinggrain` |
| `filename_equals_modelname` | `filenameequalsmodelname` |

## CLI

```
sqlmesh-ff lint [--project PATH] [--config PATH] [--checks CHECK,...] [--fail-level error|warning] [--group-by connascence|model]
```

- **Default:** all enabled checks plus SQLMesh linter rules
- **`--checks layer_integrity,custom_exclusions`:** run subset (for pre-push hooks)
- **`--fail-level warning`:** treat warnings as failures
- **`--group-by connascence|model`:** change how violations are grouped in the report (default: `connascence`)

## Integration example

Example overrides. `api_request` should always be named `api_call`. `_id` columns should always be of type `text` and `is_` columns should always be of type `boolean`.

```yaml
column_names:
  replacements:
    api_request: api_call
column_types:
  rules:
    - name: id_is_text
      pattern: "_id$"
      data_type: text
    - name: boolean
      pattern: "^is_"
      data_type: boolean
```

## Development

Initialize your local environment and configure the Git pre-push hook:
```bash
make init
```

Run linter, tests, or check diff coverage:
```bash
make lint
make test
make coverage
```

### Releases and PR titles

Releases are automated with [release-please](https://github.com/googleapis/release-please) on merges to `main`. Use [Conventional Commits](https://www.conventionalcommits.org/) in PR titles so changelog entries and semver bumps are correct.

PR titles must start with a type prefix, for example:

- `feat: add dependency graph fan-in check`
- `fix: remove unused import in loader tests`
- `docs: document fitness_functions.yaml merge order`
- `ci: add release-please workflow`

Supported types include `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, and `chore`. The PR title check in CI enforces this format.
