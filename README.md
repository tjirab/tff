# TFF: Transformation Fitness Functions

[![PyPI version](https://img.shields.io/pypi/v/tff-core.svg?logo=pypi)](https://pypi.org/project/tff-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/tff-core.svg?logo=python)](https://pypi.org/project/tff-core/)

Configurable fitness functions engine and linter for transformation projects. 

TFF allows you to enforce architectural layout boundaries, layer structure policies, schema contracts, and code formatting rules across data pipelines. It ships with dedicated plugins for **SQLMesh** and **dbt** and outputs clean, color-coded lint reports to the terminal.

<img width="1280" height="708" alt="20260629_tff-health" src="https://github.com/user-attachments/assets/2302a3dc-595f-4726-94ba-6c2aaf838bd4" />

<details>
<summary>More screenshots</summary>

#### tff lint
<img width="1280" height="570" alt="20260629_tff-lint" src="https://github.com/user-attachments/assets/2abf306d-bfc1-4c1e-a67c-31a0c97a69c8" />

#### tff info
<img width="672" height="326" alt="20260629_tff-info" src="https://github.com/user-attachments/assets/8426540f-da9d-4bc1-8d73-ea12c0553c6c" />

#### CTE fingerprinting demo
<img width="1600" height="292" alt="20260630_cte-fingerprinting" src="https://github.com/user-attachments/assets/403976e8-e88b-48cc-a632-2273902fcea2" />

</details>

---

## Documentation

Setup and usage details differ depending on your pipeline engine. Refer to the corresponding guide:

* 📐 **SQLMesh Integration**: See [docs/sqlmesh.md](docs/sqlmesh.md)
* ⚡ **dbt Integration**: See [docs/dbt.md](docs/dbt.md)
* 🔍 **Rules & Checks Reference**: See [docs/rules_and_checks.md](docs/rules_and_checks.md)
* 🏗️ **Architecture & Contributor Guide**: See [docs/contributing.md](docs/contributing.md)

---

## Quick Installation

Install the adapter matching your pipeline tool:

### 📐 For SQLMesh projects:
```bash
# With uv:
uv add tff-sqlmesh

# Or pip:
pip install tff-sqlmesh
```

### ⚡ For dbt projects:
```bash
# With uv:
uv add tff-dbt

# Or pip:
pip install tff-dbt
```


---

## CLI Usage Guide

Once installed, use the unified `tff` CLI to run linting and health checks.

```bash
tff [command] [options]
```

### Subcommands

* **`lint`**: Run all enabled fitness checks and format lint reports.
* **`health`**: Calculate and report overall project fitness health scores.
* **`info`**: Show diagnostic information about the project environment, configuration files, and adapter versions.
* **`help`**: Print help information for the CLI or specific subcommands.

### Common Options

For detailed option explanations, run `tff help <command>` or `tff <command> --help`.

#### `tff lint`
* `--project PATH`: Path to the project root directory (default: current directory).
* `--config PATH`: Path to `fitness_functions.yaml` relative to project root (default: `fitness_functions.yaml`).
* `--provider {auto,dbt,sqlmesh}`: Pipeline engine provider (default: auto-detected).
* `--checks CHECKS`: Comma-separated list of specific checks to run (default: all enabled).
* `--fail-level {error,warning}`: Exit non-zero when findings at or above this severity exist (default: `error`).
* `--group-by {connascence,model}`: How to group violations in the report (default: `model`).
* `--dialect DIALECT`: SQL dialect of models (dbt only; auto-inferred by default).

#### `tff health`
* `--project PATH`, `--config PATH`, `--provider {auto,dbt,sqlmesh}`, `--dialect DIALECT`: (Same as above)
* `--fail-under SCORE`: Exit non-zero when overall health score (0.0 - 100.0) is below this threshold (default: `0.0`).
* `--scope PATH_PREFIX [...]`: Restrict the health report to models whose path starts with one of the given prefixes (e.g. `models/sources` or `models/marts/marketing`). Multiple prefixes can be provided.
* `--group-by {connascence,domain}`: How to group the detailed health breakdown. `connascence` (default) groups by connascence category; `domain` groups by path segment under `models/` (e.g. `models/sources`, `models/marts/marketing`).

#### `tff info`
* `--project PATH`: Path to the project root directory (default: current directory).
* `--config PATH`: Path to `fitness_functions.yaml` relative to project root (default: `fitness_functions.yaml`).
* `--provider {auto,dbt,sqlmesh}`: Pipeline engine provider (default: auto-detected).

### Quick Start Examples

Run linting on the current project:
```bash
tff lint
```

Show project health report and require a score of at least 80% to pass:
```bash
tff health --fail-under 80
```

Show health scores only for the `models/marts/marketing` domain:
```bash
tff health --scope models/marts/marketing
```

Group health breakdown by domain instead of connascence category:
```bash
tff health --group-by domain
```

Combine domain scoping and grouping:
```bash
tff health --scope models/marts --group-by domain
```

Show configuration, adapter versions, and provider files for the current project:
```bash
tff info
```

Get detailed help for the `lint` subcommand:
```bash
tff help lint
# or
tff lint --help
```

---

## Core Features

TFF runs two categories of quality guardrails (for full configuration details, see the [Rules & Checks Reference](docs/rules_and_checks.md)):

### 1. Architectural Checks
* **[Layer integrity](docs/rules_and_checks.md#layer-integrity-layer_integrity)**: Prevent models in upstream layers (e.g. `marts`) from depending on downstream/raw layers.
* **[Custom exclusions](docs/rules_and_checks.md#custom-exclusions-custom_exclusions)**: Enforce custom domain isolation boundaries (e.g., prevent `marts/finance` from depending on `marts/marketing`).
* **[Schema contracts](docs/rules_and_checks.md#schema-contracts-schema_contracts)**: Ensure matching structures between model schemas (e.g., source tables and target core columns).
* **[Dependency graph](docs/rules_and_checks.md#dependency-graph-dependency_graph)**: Track DAG metrics and fail if model fan-in or fan-out exceeds defined thresholds.
* **[Materialization depth](docs/rules_and_checks.md#materialization-depth-materialization_depth)**: Prevent deep nesting of views that degrades query performance.
* **[Duplicate CTEs](docs/rules_and_checks.md#duplicate-ctes-duplicate_ctes)**: Detect duplicate complex transformation logic in CTEs across different models (Connascence of Algorithm).

### 2. Linter Rules
* **[Ban `SELECT *`](docs/rules_and_checks.md#ban-select-ban_select_star)**: Require explicit columns to reduce upstream coupling.
* **[No positional GROUP BY/ORDER BY](docs/rules_and_checks.md#no-positional-group-byorder-by-no_positional_group_by_or_order_by)**: Prevent using ordinal indexes (e.g., `GROUP BY 1, 2`) in queries.
* **[Classification macros](docs/rules_and_checks.md#classification-macros-classification_macros)**: Require using standardized macros instead of inline CASE statements for classification fields.
* **[Sql complexity](docs/rules_and_checks.md#sql-complexity-sql_complexity)**: Limits CTE count, join count, decision points, and line count in SQL.
* **[Mart naming](docs/rules_and_checks.md#mart-naming-mart_naming)**: Ensure model filenames match their subfolder namespaces.
* **[Column names](docs/rules_and_checks.md#column-names-column_names)**: Avoid deprecated or forbidden patterns in column names.
* **[Column types](docs/rules_and_checks.md#column-types-column_types)**: Enforce expected types for matching column name patterns.
* **[Metadata checks](docs/rules_and_checks.md#metadata-metadata)**: Enforce owners, descriptions, grains, unique assertions, and non-null constraints on models.
* **[Filename equals model name](docs/rules_and_checks.md#filename-equals-model-name-filename_equals_modelname)**: Flags model name mismatch.
* **[Environment agnostic references](docs/rules_and_checks.md#environment-agnostic-references-environment_agnostic_references)**: Ban hardcoded environment/catalog prefixes in queries.

---

## Shared Configuration

All adapters use a shared `fitness_functions.yaml` config file located in the root of your project:

```yaml
contract_groups_path: linter_contract_groups.json
exclusions_path: linter_exclusions.json

layers:
  order: [staging, core, marts]  # Configured bottom-to-top hierarchy

checks:
  layer_integrity: { enabled: true }
  custom_exclusions: { enabled: true }
  schema_contracts: { enabled: true }
  dependency_graph:
    enabled: true
    fan_out_warn: 15
    fan_out_fail: 25
    fan_in_warn: 10
  duplicate_ctes:
    enabled: true
    severity: warning
    min_ast_nodes: 12

rules:
  ban_select_star:
    enabled: true
  no_positional_group_by_or_order_by:
    enabled: true
  environment_agnostic_references:
    enabled: true
    banned_environments: [prod, dev, staging, uat, qa]
  classification_macros:
    enabled: true
    skip_layers: [staging]
    columns:
      product_type: "@product_type\\b"
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
    replacements:
      api_request: api_call
  column_types:
    enabled: true
    rules:
      - name: id_is_text
        pattern: "_id$"
        data_type: text
  metadata:
    owner: true
    description: true
    grain: true
    unique_values: true
    not_null: true
  filename_equals_modelname:
    enabled: true
```

---

## Further Reading & Learning Resources

To learn more about the architectural concepts behind fitness functions and connascence, check out these resources:

* [Connascence.io](https://connascence.io/) — A guide to software coupling metrics (connascence of name, type, meaning, algorithm, etc.), which inspired the classification and structure of the linter report findings.
* [Evolutionary Architecture](https://evolutionaryarchitecture.com/) — The homepage for *Building Evolutionary Architectures*, which introduces the concept of architectural fitness functions to guide design changes over time.
