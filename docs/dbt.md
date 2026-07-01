# Using TFF with dbt

TFF integrates with [dbt](https://www.getdbt.com) using the `tff-dbt` package. Rather than running at query time, it inspects your compiled dbt project manifest to run linter rules and architectural validation.

---

## Installation

Install the dbt adapter:

```bash
# With uv:
uv add tff-dbt

# Or pip:
pip install tff-dbt
```

---

## Quick Start

1. Add `fitness_functions.yaml` to your dbt project root.
2. Compile your dbt project to generate the manifest file:
   ```bash
   dbt compile
   ```
3. Run the linter CLI:
   ```bash
   tff lint
   ```

---

## How It Works

The `tff-dbt` linter reads `target/manifest.json` relative to your project root. It maps dbt resource nodes into a generic representations to run adapter-agnostic rule checks:

### 1. Model & Source Mapping
* **Models, Seeds, and Snapshots** are mapped to active models.
* **Sources and External Tables** are mapped as external models (skipped for code styling rules but included in dependency graph analysis).
* **Ephemeral Models** are mapped as symbolic models.

### 2. Schema Test to Audit Mapping
dbt represents tests as independent nodes in the DAG. TFF parses these test nodes (like `not_null`, `unique`, or `accepted_values`) and maps them back to the target model's `audits` list. This enables rules like `nomissinguniquevalues` and `nomissingnotnull` to evaluate model schemas correctly.

### 3. Layer and Domain Mapping
TFF infers the layer of a model from its folder path relative to the `models/` directory:
* `models/staging/stg_users.sql` $\rightarrow$ layer: `staging`
* `models/marts/marketing/all_users.sql` $\rightarrow$ layer: `marts`, domain: `marketing`

This layer and domain structure is evaluated against your `layers.order` configuration and the custom layer isolation boundaries.

---

## CLI Options

### `tff lint`

```bash
tff lint [--project PATH] [--config PATH] [--provider PROVIDER] [--checks CHECK,...] [--fail-level error|warning] [--group-by connascence|model] [--dialect DIALECT]
```

* **`--project`**: Path to your project root (default: current directory).
* **`--config`**: Path to `fitness_functions.yaml` (default: `fitness_functions.yaml`).
* **`--provider`**: The pipeline engine provider: `auto`, `dbt`, or `sqlmesh` (default: `auto`).
* **`--dialect`**: The SQL dialect used by your data warehouse, used for SQL parsing checks (dbt only; default: auto-inferred).
* **`--checks`**: Comma-separated list of active checks to execute.
* **`--fail-level`**: Exit non-zero when findings at or above this severity exist (`error` or `warning`, default: `error`).
* **`--group-by`**: Changes report grouping format (`connascence` or `model`, default: `model`).

### `tff health`

```bash
tff health [--project PATH] [--config PATH] [--provider PROVIDER] [--dialect DIALECT] [--fail-under SCORE] [--scope PATH_PREFIX ...] [--group-by connascence|domain]
```

* **`--project`**: Path to your project root (default: current directory).
* **`--config`**: Path to `fitness_functions.yaml` (default: `fitness_functions.yaml`).
* **`--provider`**: The pipeline engine provider: `auto`, `dbt`, or `sqlmesh` (default: `auto`).
* **`--dialect`**: SQL dialect for parsing (dbt only; default: auto-inferred).
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

