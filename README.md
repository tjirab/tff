# TFF: Transformation Fitness Functions

[![PyPI version](https://img.shields.io/pypi/v/tff-core.svg)](https://pypi.org/project/tff-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/tff-core.svg)](https://pypi.org/project/tff-core/)

Configurable fitness functions engine and linter for transformation projects. 

TFF allows you to enforce architectural layout boundaries, layer structure policies, schema contracts, and code formatting rules across data pipelines. It ships with dedicated plugins for **SQLMesh** and **dbt** and outputs clean, color-coded lint reports to the terminal.
<img width="1029" height="828" alt="Screenshot 2026-06-27 at 13 22 08" src="https://github.com/user-attachments/assets/77c8896f-b626-481e-90f1-b88fe8036448" />

---

## Documentation

Setup and usage details differ depending on your pipeline engine. Refer to the corresponding guide:

* 📐 **SQLMesh Integration**: See [docs/sqlmesh.md](docs/sqlmesh.md)
* ⚡ **dbt Integration**: See [docs/dbt.md](docs/dbt.md)
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

## Core Features

TFF runs two categories of quality guardrails:

### 1. Architectural Checks
* **Layer integrity**: Prevent models in upstream layers (e.g. `marts`) from depending on downstream/raw layers.
* **Custom exclusions**: Enforce custom domain isolation boundaries (e.g., prevent `marts/finance` from depending on `marts/marketing`).
* **Schema contracts**: Ensure matching structures between model schemas (e.g., source tables and target core columns).
* **Dependency graph**: Track DAG metrics and fail if model fan-in or fan-out exceeds defined thresholds.

### 2. Linter Rules
* **No SELECT ***: Require explicit columns to reduce upstream coupling.
* **No positional GROUP BY/ORDER BY**: Prevent using ordinal indexes (e.g., `GROUP BY 1, 2`) in queries.
* **Classification macros**: Require using standardized macros instead of inline CASE statements for classification fields.
* **Sql complexity**: Limits CTE count, join count, decision points, and line count in SQL.
* **Mart naming**: Ensure model filenames match their subfolder namespaces.
* **Metadata checks**: Enforce owners, descriptions, grains, unique assertions, and non-null constraints on models.
* **Filename equals model name**: Flags model name mismatch.

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

rules:
  no_select_star:
    enabled: true
  no_positional_group_by_or_order_by:
    enabled: true
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
