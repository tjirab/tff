# Rules and Checks Reference

TFF runs two categories of quality guardrails: **Architectural Checks** and **Linter Rules**. All of these are configured in the `fitness_functions.yaml` file in the root of your project.

---

## Shared Layer Filtering Configuration

Most checks and rules inherit a common layer filtering schema. This allows you to apply guardrails selectively based on the pipeline layer a model belongs to:

```yaml
rules:
  some_rule:
    enabled: true             # Toggle the rule on or off (default: true)
    skip_layers: [staging]    # List of layers where this rule should NOT run
    only_layers: [marts]      # If specified, the rule ONLY runs on these layers
```

---

## 1. Architectural Checks

Architectural checks evaluate the structure, dependencies, and layout of your entire project DAG. They are run via the `tff lint` or `tff health` CLI commands.

### Layer Integrity (`layer_integrity`)

* **What it checks**:
  * **Unidirectional Dependency Flow**: Ensures models in upstream layers do not depend on models in downstream layers (as defined by the index order in `layers.order`).
  * **Mart Domain Isolation**: Ensures models within the `marts` layer (models/marts) do not depend on models in other domains within the `marts` layer (e.g., `models/marts/finance` cannot depend on `models/marts/marketing`).
* **How to configure**:
  Defined under `checks.layer_integrity` in `fitness_functions.yaml`.
  ```yaml
  layers:
    order: [staging, core, marts]  # Bottom-to-top hierarchy order

  checks:
    layer_integrity:
      enabled: true
  ```
  Layers are located at the first level within the models/ directory, e.g. `order: [staging, core, marts]` assumes `models/staging`, `models/core`, and `models/marts` directories. These can contain subdirectories with models.

---

### Custom Exclusions (`custom_exclusions`)

* **What it checks**:
  * Enforces custom dependency boundaries defined in a separate JSON file. It blocks defined layer/domain dependencies and supports specifying whitelist exceptions.
* **How to configure**:
  Defined under `checks.custom_exclusions` in `fitness_functions.yaml`.
  ```yaml
  exclusions_path: linter_exclusions.json  # Relative to project root

  checks:
    custom_exclusions:
      enabled: true
  ```
  The exclusions file (e.g., `linter_exclusions.json`) has the following structure:
  ```json
  {
    "exclusions": [
      {
        "source_layer": "core",
        "target_layer": "derived"
      },
      {
        "source_layer": "core",
        "source_domain": "finance",
        "target_layer": "marts",
        "target_domain": "marketing"
      }
    ],
    "allowed_exceptions": [
      {
        "model": "derived.model_name",
        "dependency": "core.dependency_name"
      }
    ]
  }
  ```
  * **`exclusions`**: A list of blocked dependencies. If a model in the `target_layer`/`target_domain` depends on a model in the `source_layer`/`source_domain` (which is the source of the dependency relation), a violation is raised. Omitting domain fields matches all domains in that layer.
  * **`allowed_exceptions`**: Specific `model` $\rightarrow$ `dependency` pairs to allow even if they match an exclusion rule.

---

### Schema Contracts (`schema_contracts`)

* **What it checks**:
  * Enforces schema structural parity between related models to ensure they stay in sync.
* **How to configure**:
  Defined under `checks.schema_contracts` in `fitness_functions.yaml`.
  ```yaml
  contract_groups_path: linter_contract_groups.json  # Relative to project root

  checks:
    schema_contracts:
      enabled: true
  ```
  The schema contracts file (e.g., `linter_contract_groups.json`) supports two contract formats:
  
  #### 1. Column Parity Groups
  Enforces that member models contain the exact same columns in the exact same order as a reference model.
  ```json
  {
    "column_parity_groups": [
      {
        "models_dir": "models/core",
        "reference": "dim_customer_ref.sql",
        "exclude_columns": ["created_at", "updated_at"],
        "reference_substitutions": {
          "customer_id": "id"
        },
        "members": [
          {
            "file": "dim_customer_replica.sql",
            "substitutions": {
              "cust_id": "id"
            }
          }
        ]
      }
    ]
  }
  ```
  * `models_dir`: The base directory within the project root for the files.
  * `reference`: The SQL file of the source-of-truth model.
  * `exclude_columns` (optional): Columns to ignore in the comparison.
  * `reference_substitutions` (optional): Maps reference columns to a common name for comparison.
  * `members`: The list of member models. Each member can define own `substitutions` to align column names.

  #### 2. Dimension Parity Groups
  Enforces that two models contain the exact same set of dimension columns, regardless of their select order.
  ```json
  {
    "dimension_parity_groups": [
      {
        "models_dir": "models/core",
        "left": {
          "file": "fact_sales.sql",
          "exclude_columns": ["revenue"]
        },
        "right": {
          "file": "fact_orders.sql",
          "exclude_columns": ["quantity"]
        }
      }
    ]
  }
  ```
  * `left` / `right`: The configuration for each of the two models to compare, along with optional column exclusions.

---

### Dependency Graph (`dependency_graph`)

* **What it checks**:
  * Monitors the DAG shape for high coupling. It tracks:
    * **`fan_in` (Inward Coupling)**: The number of upstream models that *this* model directly depends on.
    * **`fan_out` (Outward Coupling / Blast Radius)**: The number of downstream models that depend on this model.
* **How to configure**:
  Defined under `checks.dependency_graph` in `fitness_functions.yaml`.
  ```yaml
  checks:
    dependency_graph:
      enabled: true
      fan_out_warn: 15
      fan_out_fail: 25
      fan_in_warn: 10
      skip_layers: [staging]
  ```
  * `fan_out_warn` (int, default: 15): Warn if a model's fan-out is higher than this value.
  * `fan_out_fail` (int, default: 25): Fail (raise an error) if a model's fan-out is higher than this value.
  * `fan_in_warn` (int, default: 10): Warn if a model's fan-in is higher than this value.

---

### Materialization Depth (`materialization_depth`)

* **What it checks**:
  * Calculates the nesting depth of SQL models materialized as `view`. Views built on other views incur overhead.
  * A view's depth is calculated recursively: `1 + max(depth of view dependencies)`.
  * Non-views (e.g., `table`, `incremental`, or `seed` models) reset the depth calculation and have a depth of `0`.
* **How to configure**:
  Defined under `checks.materialization_depth` in `fitness_functions.yaml`.
  ```yaml
  checks:
    materialization_depth:
      enabled: true
      max_depth_warn: 3
      max_depth_fail: 5
      skip_layers: [staging]
  ```
  * `max_depth_warn` (int, default: 3): Warn if nesting depth exceeds this.
  * `max_depth_fail` (int, default: 5): Raise an error if nesting depth exceeds this.

---

### Duplicate CTEs (`duplicate_ctes`)

* **What it checks**:
  * Identifies "Connascence of Algorithm" by flagging duplicate or near-identical transformation logic inside CTEs across different models.
  * CTEs are parsed, canonicalized using `sqlglot` to ignore whitespace/formatting differences, and hashed.
  * Only "complex" CTEs are checked. A CTE is complex if it has a minimum AST node count and contains a structural element (`JOIN`, `WHERE`, `GROUP BY`, `HAVING`, `WINDOW`, `CASE`, or `IF`).
* **How to configure**:
  Defined under `checks.duplicate_ctes` in `fitness_functions.yaml`.
  ```yaml
  checks:
    duplicate_ctes:
      enabled: true
      severity: warning      # Severity of finding: 'warning' or 'error'
      min_ast_nodes: 12      # Minimum AST node count to analyze (default: 12)
      skip_layers: [staging]
  ```

---

## 2. Linter Rules

Linter rules inspect individual model files to enforce code style, conventions, and database-independent references.

For SQLMesh projects, these rules run dynamically inside SQLMesh (e.g., `sqlmesh lint`) using the lowercase class name.

---

### Ban SELECT * (`ban_select_star`)

* **What it checks**:
  * Disallows the use of wildcard `SELECT *` statements. Requires explicit column naming to reduce model coupling.
* **How to configure**:
  Defined under `rules.ban_select_star` in `fitness_functions.yaml`.
  ```yaml
  rules:
    ban_select_star:
      enabled: true
      skip_layers: [sources]
  ```
  * **SQLMesh Rule Name**: `banselectstar`
  * Default `skip_layers`: `["sources"]`

---

### No Positional GROUP BY/ORDER BY (`no_positional_group_by_or_order_by`)

* **What it checks**:
  * Prevents using ordinal integers (e.g., `GROUP BY 1, 2` or `ORDER BY 1 DESC`) instead of explicit column name references.
* **How to configure**:
  Defined under `rules.no_positional_group_by_or_order_by` in `fitness_functions.yaml`.
  ```yaml
  rules:
    no_positional_group_by_or_order_by:
      enabled: true
      skip_layers: [sources]
  ```
  * **SQLMesh Rule Name**: `nopositionalgroupbyororderby`
  * Default `skip_layers`: `["sources"]`

---

### Environment Agnostic References (`environment_agnostic_references`)

* **What it checks**:
  * Blocks hardcoded references to specific database catalog or schema names (like `prod.database.table`).
  * Table references are parsed, and the non-table prefixes are scanned case-insensitively against the banned list.
* **How to configure**:
  Defined under `rules.environment_agnostic_references` in `fitness_functions.yaml`.
  ```yaml
  rules:
    environment_agnostic_references:
      enabled: true
      banned_environments: [prod, dev, staging, uat, qa]
  ```
  * **SQLMesh Rule Name**: `environmentagnosticreferences`
  * `banned_environments` (list of strings, default: `["prod", "dev", "staging", "uat", "qa"]`): Environment strings to block.

---

### Classification Macros (`classification_macros`)

* **What it checks**:
  * Enforces "Connascence of Meaning" by requiring classification columns to use standard macros instead of inline `CASE` statements.
  * If a query defines an inline `CASE ... END AS <column>` matching a key in `columns`, it flags a violation unless the corresponding macro pattern is matched in the query.
* **How to configure**:
  Defined under `rules.classification_macros` in `fitness_functions.yaml`.
  ```yaml
  rules:
    classification_macros:
      enabled: true
      skip_layers: [sources]
      columns:
        product_type: "@product_type\\b"
        billing_segment: "@BILLING_SEGMENT\\b"
  ```
  * **SQLMesh Rule Name**: `classificationmacros`
  * `columns`: A dictionary mapping target column names to regex patterns matching their expected macro representations.
  * Default `skip_layers`: `["sources"]`

---

### SQL Complexity (`sql_complexity`)

* **What it checks**:
  * Evaluates maintainability metrics of a model query:
    * `cte_count`: Number of common table expressions.
    * `join_count`: Number of `JOIN` statements.
    * `line_count`: Total lines of code (ignoring empty lines and SQLMesh `MODEL` blocks).
    * `decision_points`: Number of logical conditional statements (`CASE`, `IF` and boolean operators `AND`/`OR` in `WHERE` clauses).
    * `nested_subquery_in_final_select`: Warns if a subquery is nested in the final SELECT statement FROM clause.
* **How to configure**:
  Defined under `rules.sql_complexity` in `fitness_functions.yaml`.
  ```yaml
  rules:
    sql_complexity:
      enabled: true
      warn_only: true
      thresholds:
        decision_points: [15, 25]  # [warn_threshold, fail_threshold]
        cte_count: [8, 12]
        join_count: [8, 12]
        line_count: [250, 400]
  ```
  * **SQLMesh Rule Name**: `sqlcomplexity`
  * `warn_only` (bool, default: `true`): If `true`, metrics exceeding warning limits but under failure limits raise warnings only.
  * `thresholds`: Map of metric to `[warn_threshold, fail_threshold]` integer pairs.

---

### Mart Naming (`mart_naming`)

* **What it checks**:
  * Enforces naming conventions for models residing inside subfolders of the `marts` layer directory.
  * Ensures that the filename starts with the name of the subfolder directory (e.g., `marts/marketing/ad_performance.sql` should be named `marketing_ad_performance.sql`).
* **How to configure**:
  Defined under `rules.mart_naming` in `fitness_functions.yaml`.
  ```yaml
  rules:
    mart_naming:
      enabled: true
      layer_name: marts
      rule: prefix_with_subdirectory
  ```
  * **SQLMesh Rule Name**: `martmodelnamingconvention`
  * `layer_name` (string, default: `"marts"`): Folder name of the marts layer.
  * `rule` (string, default: `"prefix_with_subdirectory"`): Naming rule to enforce.

---

### Column Names (`column_names`)

* **What it checks**:
  * Enforces naming standards on column columns by checking for deprecations or forbidden substrings.
* **How to configure**:
  Defined under `rules.column_names` in `fitness_functions.yaml`.
  ```yaml
  rules:
    column_names:
      enabled: true
      replacements:
        api_request: api_call
        cust_id: customer_id
  ```
  * **SQLMesh Rule Name**: `columnnames`
  * `replacements`: A dictionary mapping search regex patterns (deprecated names) to target replacement suggestions.

---

### Column Types (`column_types`)

* **What it checks**:
  * Ensures columns matching specific name patterns are defined with expected data types (e.g., columns ending in `_id` must be typed as `text`).
* **How to configure**:
  Defined under `rules.column_types` in `fitness_functions.yaml`.
  ```yaml
  rules:
    column_types:
      enabled: true
      rules:
        - name: id_is_text
          pattern: "_id$"
          data_type: text
      equivalent_types:
        text: [text, varchar]
  ```
  * **SQLMesh Rule Name**: `columntypes`
  * `rules`: A list of rule entries containing:
    * `name`: Identifier of the rule.
    * `pattern`: Regex matching column names.
    * `data_type`: Expected SQL data type.
  * `equivalent_types`: A dictionary of synonym types mapping an expected type to list of accepted equivalent strings.

---

### Metadata (`metadata`)

* **What it checks**:
  * Enforces model metadata documentation and testing:
    * **`owner`**: Validates that the model config has a specified owner.
    * **`description`**: Validates that the model description is defined and non-empty.
    * **`grain`**: Validates that grains (primary key/grain definition) are specified.
    * **`not_null`**: Validates that the model has a `not_null` audit (SQLMesh) or test (dbt).
    * **`unique_values`**: Validates that the model has a `unique_values` audit (SQLMesh) or `unique` test (dbt).
* **How to configure**:
  Defined under `rules.metadata` in `fitness_functions.yaml`.
  ```yaml
  rules:
    metadata:
      enabled: true
      owner: true
      description: true
      grain: true
      not_null: true
      unique_values: true
  ```
  * **SQLMesh Rule Names**: Runs as five separate rules:
    * `nomissingowner`
    * `nomissingdescription`
    * `nomissinggrain`
    * `nomissingnotnull`
    * `nomissinguniquevalues`

---

### Filename Equals Model Name (`filename_equals_modelname`)

* **What it checks**:
  * Validates that the model's catalog identifier matches the stem of its source SQL file on disk.
* **How to configure**:
  Defined under `rules.filename_equals_modelname` in `fitness_functions.yaml`.
  ```yaml
  rules:
    filename_equals_modelname:
      enabled: true
  ```
  * **SQLMesh Rule Name**: `filenameequalsmodelname`
