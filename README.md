# TFF: Transformation Fitness Functions

[![PyPI version](https://img.shields.io/pypi/v/tff-core.svg?logo=pypi)](https://pypi.org/project/tff-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/tff-core.svg?logo=python)](https://pypi.org/project/tff-core/)

Configurable fitness functions engine and linter for transformation projects. 

TFF allows you to enforce architectural layout boundaries, layer structure policies, schema contracts, and code formatting rules across data pipelines. It ships with dedicated plugins for **SQLMesh**, **dbt**, and **Google Cloud Dataform**, outputting clean, color-coded lint reports to the terminal.

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
* ☁️ **Dataform Integration**: See [docs/dataform.md](docs/dataform.md)
* 💻 **CLI Reference Guide**: See [docs/cli.md](docs/cli.md)
* 🤖 **CI/CD & GitHub Actions Guide**: See [docs/ci_cd.md](docs/ci_cd.md)
* 🔍 **Rules & Checks Reference**: See [docs/rules_and_checks.md](docs/rules_and_checks.md)
* 📊 **Case Study: GitLab dbt Audit (2,200+ models)**: See [docs/case_study_gitlab.md](docs/case_study_gitlab.md)
* 🏗️ **Architecture & Contributor Guide**: See [docs/contributing.md](docs/contributing.md)

---

## Quick Installation

Install the package with the adapter matching your pipeline tool:

### 📐 For SQLMesh projects:
```bash
# With uv:
uv add "tff-core[sqlmesh]"

# Or pip:
pip install "tff-core[sqlmesh]"
```

### ⚡ For dbt projects:
```bash
# With uv:
uv add "tff-core[dbt]"

# Or pip:
pip install "tff-core[dbt]"
```

### ☁️ For Dataform projects:
```bash
# With uv:
uv add "tff-core[dataform]"
# (or simply: uv add tff-core)

# Or pip:
pip install "tff-core[dataform]"
```


---

## CLI Usage Guide

Once installed, use the unified `tff` CLI to run linting, calculate health scores, and enforce architectural quality gates:

```bash
tff [command] [options]
```

### Commands Overview

| Command | Description | Quick Example |
| :--- | :--- | :--- |
| **`lint`** | Run architectural fitness checks and output lint reports | `tff lint --fix` |
| **`health`** | Calculate overall project fitness health score (0–100) | `tff health --fail-under 80` |
| **`action`** | Run official GitHub Action pipeline (score, diff, PR comments) | `tff action --only-changed` |
| **`docs`** | Generate standalone interactive HTML dashboard with lineage graphs | `tff docs --output docs/index.html` |
| **`init`** | Scaffold an annotated starter `fitness_functions.yaml` file | `tff init` |
| **`stats`** | View historical fitness check execution trends and logs | `tff stats --days 30` |
| **`info`** | Inspect project environment, config, and adapter versions | `tff info` |
| **`help`** | Show detailed help and options for any command | `tff help lint` |

### Quick Start Examples

```bash
# Lint current project (zero-config out of the box)
tff lint

# Automatically fix simple linting violations
tff lint --fix

# Require an 80% health score to pass CI
tff health --fail-under 80

# Restrict health scoring to a specific domain
tff health --scope models/marts/marketing

# Generate interactive HTML dashboard
tff docs

# Export SARIF for GitHub Code Scanning
tff lint --format sarif > results.sarif
```

👉 **For the complete CLI reference, detailed option tables for every command, output formats, and cookbooks, see the [CLI Reference Guide](docs/cli.md).**

---

## CI/CD & Automated Quality Gates

TFF integrates seamlessly into modern data engineering CI/CD pipelines to enforce architectural fitness functions, calculate health scores, and gate pull requests.

### Official GitHub Action (`tjirab/tff@v1`)

Run TFF on pull requests with zero virtualenv setup. The action automatically installs the required engine adapter, gates merges based on health thresholds, emits inline annotations on modified lines, and posts interactive summary comments:

```yaml
name: TFF Architectural Fitness Functions

on:
  pull_request:
    branches: [ main ]

jobs:
  tff-check:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write  # Required for posting/updating PR summary comments
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Required to compute health score diff vs base branch

      - name: Run TFF Action
        uses: tjirab/tff@v1
        with:
          provider: "auto"       # auto, dbt, sqlmesh, or dataform
          fail-under: "80.0"     # Minimum health score to pass (0-100)
          fail-level: "error"    # Failure severity level (error, warning)
          only-changed: "true"   # 👈 Only gate models modified in this PR
          comment-pr: "true"     # Post/update PR health summary comment
```

👉 **For the complete guide, full input/output reference tables, GitLab CI, and SARIF exports, see the [CI/CD & GitHub Actions Guide](docs/ci_cd.md).**

---

## Pre-commit Integration

TFF includes native [pre-commit](https://pre-commit.com/) hooks to validate or auto-fix violations locally before commits are created:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/tjirab/tff
    rev: v0.12.1
    hooks:
      - id: tff-lint
      # Or automatically fix simple violations:
      # - id: tff-lint-fix
```

For SQLMesh projects or advanced pre-commit dependency configurations, refer to the [CI/CD Documentation](docs/ci_cd.md#2-pre-commit-hooks-integration).

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
* **[Connascence of Value](docs/rules_and_checks.md#connascence-of-value-connascence_of_value)**: Identify duplicated domain-meaning literal values (strings, numbers) across multiple models (Connascence of Value).

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
# Schema contracts and custom exclusions can be configured directly in YAML
# (or loaded from external JSON files via contract_groups_path / exclusions_path)
exclusions:
  - source_layer: core
    target_layer: derived

contract_groups:
  column_parity_groups:
    - reference: models/core/dim_customer_ref.sql
      members: [models/core/dim_customer_replica.sql]

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
  connascence_of_value:
    enabled: true
    severity: warning
    min_occurrences: 2

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

# Configurable health scoring weights and failure penalties
health:
  weights:
    layer_integrity: 3.0
    schema_contracts: 2.0
    column_names: 0.5
  penalties:
    error: 1.0
    warning: 0.5
    project_error: 100.0
    project_warning: 50.0
```

---

## Further Reading & Learning Resources

To learn more about the architectural concepts behind fitness functions and connascence, check out these resources:

* [Connascence.io](https://connascence.io/) — A guide to software coupling metrics (connascence of name, type, meaning, algorithm, etc.), which inspired the classification and structure of the linter report findings.
* [Evolutionary Architecture](https://evolutionaryarchitecture.com/) — The homepage for *Building Evolutionary Architectures*, which introduces the concept of architectural fitness functions to guide design changes over time.
