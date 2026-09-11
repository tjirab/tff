# Rules and Checks Reference

TFF runs two categories of quality guardrails: **Architectural Checks** and **Linter Rules**. All of these are configured in the `fitness_functions.yaml` file in the root of your project.

---

## 🛠️ Auto-Fixer (`--fix`)

TFF includes a built-in auto-fixer that can automatically resolve simple violations. By running `tff lint --fix`, TFF will modify your source files to fix the following issues:

*   **[No Positional GROUP BY/ORDER BY](#no-positional-group-byorder-by-no_positional_group_by_or_order_by)** (`nopositionalgroupbyororderby`): Rewrites integer positional references in `GROUP BY` and `ORDER BY` clauses to explicit column names or select aliases using AST modification.
*   **Metadata (`nomissingowner`, `nomissingdescription`)**:
    *   **dbt**: Automatically appends or scaffolds `schema.yml` metadata configs with `"TODO: Add owner"` and `"TODO: Add description"` templates.
    *   **SQLMesh**: Inline-updates the `MODEL` block in the model `.sql` file to add `owner` and `description` headers.

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
  * Enforces custom dependency boundaries. It blocks defined layer/domain dependencies and supports specifying whitelist exceptions. Exclusions can be defined directly in `fitness_functions.yaml` or in a separate JSON file.
* **How to configure**:
  Defined directly under `exclusions` and `allowed_exceptions` (or under `checks.custom_exclusions`) in `fitness_functions.yaml`:
  ```yaml
  exclusions:
    - source_layer: core
      target_layer: derived
    - source_layer: core
      source_domain: finance
      target_layer: marts
      target_domain: marketing

  allowed_exceptions:
    - model: derived.model_name
      dependency: core.dependency_name

  checks:
    custom_exclusions:
      enabled: true
  ```
  Alternatively, you can point to an external JSON exclusions file (e.g. `linter_exclusions.json`):
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

  #### Metadata/Tag-driven Fallback
  If models are organized by functional theme rather than layer directories, `layer_integrity` and `custom_exclusions` will automatically fall back to using tags and metadata:
  * **Layer**: Set a tag matching one of the layers in the `layers.order` list, or define a `layer` key in model metadata.
  * **Domain**: Prefix a tag with `domain:`, e.g., `domain:finance`, or define a `domain` key in model metadata.

  **Example (Functional Theme Layout)**:
  Assume a model is located at `models/finance/payments_cleared.sql`. Since `finance` is not in your configured `layers.order`, TFF's directory parser cannot determine the layer automatically. You can explicitly tag/annotate it:
  
  * **dbt (`schema.yml`)**:
    ```yaml
    models:
      - name: payments_cleared
        config:
          tags: ["marts"]       # Layer: resolves to marts layer
          meta:
            domain: billing     # Domain: sets domain to billing
    ```
  
  * **SQLMesh (`payments_cleared.sql`)**:
    ```sql
    MODEL (
      name finance.payments_cleared,
      kind VIEW,
      tags (marts),             -- Resolves the model layer to marts
      meta (
        domain billing          -- Resolves the model domain to billing
      )
    );
    ```

  #### YAML-based Configuration
  Instead of or in addition to a JSON file, custom exclusion rules and exceptions can also be defined directly in `fitness_functions.yaml` under `checks.custom_exclusions` using tags and metadata selectors:
  ```yaml
  checks:
    custom_exclusions:
      enabled: true
      exclusions:
        # Exclude public models from depending on pii models via tags
        - source_tag: "pii"
          target_tag: "public"
        # Exclude based on metadata key-value pairs
        - source_meta:
            team: "marketing"
          target_meta:
            team: "finance"
        # Combine layer/domain with tag/meta selectors
        - source_layer: "core"
          source_tag: "confidential"
          target_layer: "marts"
      allowed_exceptions:
        - model: "marts.public_model"
          dependency: "core.confidential_model"
  ```

---

### Schema Contracts (`schema_contracts`)

* **What it checks**:
  * Enforces schema structural parity between related models to ensure they stay in sync. Contracts can be configured directly in `fitness_functions.yaml` or in an external JSON file.
* **How to configure**:
  Defined under `contract_groups` (or under `checks.schema_contracts`) in `fitness_functions.yaml`:
  ```yaml
  contract_groups:
    column_parity_groups:
      - reference: models/core/dim_customer_ref.sql
        exclude_columns: [created_at, updated_at]
        members:
          - models/core/dim_customer_replica.sql

    dimension_parity_groups:
      - left: models/core/fact_sales.sql
        right: models/core/fact_orders.sql

  checks:
    schema_contracts:
      enabled: true
  ```
  Alternatively, you can point to an external JSON contract groups file (e.g. `linter_contract_groups.json`):
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

### Connascence of Value (`connascence_of_value`)

* **What it checks**:
  * Identifies "Connascence of Value" by flagging literal values (strings, numbers) duplicated across multiple models.
  * Only domain-meaning literals are checked. Structural and technical SQL literals are automatically excluded based on AST context:
    * Literals inside `LIMIT` or `OFFSET` clauses.
    * Data type parameters and precision/scale definitions (e.g. `DECIMAL(15, 2)`, `VARCHAR(255)`).
    * Rounding and truncation precision/scale arguments (e.g. `ROUND(amount, 2)`, `TRUNC(amount, 2)`).
    * String splitting delimiter and index arguments (e.g. `SPLIT_PART(email, '@', 2)`).
    * Positional string slicing parameters (e.g. `SUBSTRING(name, 1, 10)`, `LEFT(name, 5)`, `RIGHT(name, 5)`).
    * String concatenation operators (`||` / `DPipe`) and `CONCAT_WS` separators.
    * Mathematical divisors in arithmetic division (e.g. `amount / 100.00` cents-to-dollars divisor).
  * Short punctuation characters (`|`, ` `, `-`, `_`, `/`, `:`) are ignored by default and configurable via `ignored_punctuation`.
  * Project-specific literal escapes can be added to `ignored_values`.
  * Grouping is case-insensitive for strings, but the original casing is preserved in the findings messages.
* **How to configure**:
  Defined under `checks.connascence_of_value` in `fitness_functions.yaml`.
  ```yaml
  checks:
    connascence_of_value:
      enabled: true
      severity: warning               # Severity of finding: 'warning' or 'error'
      min_occurrences: 2             # Minimum number of unique models sharing a literal to trigger (default: 2)
      ignored_values: ["0", "1", ""]  # List of literals to ignore (default: ['0', '1', ''])
      ignored_punctuation: ["|", " ", "-", "_", "/", ":"] # Punctuation strings to ignore (default: ['|', ' ', '-', '_', '/', ':'])
      skip_layers: [staging]
  ```

* **Why it matters (The "Why")**:
  Connascence of Value occurs when two or more components must share a specific value (literal/constant) to function correctly. If that value changes in the source data or business rules (e.g. `'premium_tier'` becomes `'premium_membership'`), all models containing it must be updated simultaneously. If any are missed, it silently introduces data discrepancies between your models (e.g. marketing counts new users but finance continues to filter on the old tier name).

* **Example of Duplication**:
  ```sql
  -- premium_users.sql
  SELECT * FROM {{ ref('dim_users') }} WHERE status = 'premium_tier'

  -- premium_revenue.sql
  SELECT * FROM {{ ref('finance_revenue') }} WHERE status = 'premium_tier'
  ```

* **How to Resolve**:
  1. **Upstream Classification (Recommended)**: Evaluate and rename/classify the status once in a staging layer, exposing it downstream as a simple boolean flag:
     ```sql
     -- stg_users.sql
     SELECT user_id, (status = 'premium_tier') AS is_premium FROM raw_users
     
     -- Downstream models
     SELECT * FROM {{ ref('stg_users') }} WHERE is_premium
     ```
  2. **Project-Level Variables**: Define the value as a project variable in `dbt_project.yml` and reference it via Jinja:
     ```sql
     SELECT * FROM {{ ref('stg_users') }} WHERE status = '{{ var("premium_tier_name") }}'
     ```
  3. **Mapping Tables (Seeds)**: For larger sets of constants (e.g., list of VIP email domains), load them via a seed CSV and perform a `JOIN` or `WHERE IN (SELECT ... FROM {{ ref('seed') }})`.

---

## 2. Linter Rules

Linter rules inspect individual model files to enforce code style, conventions, and database-independent references.

For SQLMesh projects, these rules run dynamically inside SQLMesh (e.g., `sqlmesh lint`) using the lowercase class name.

---

### Ban SELECT * (`ban_select_star`)

* **What it checks**:
  * Disallows the use of wildcard `SELECT *` statements. Requires explicit column naming to reduce model coupling. Aggregate count expressions (e.g., `COUNT(*)`, `COUNT(DISTINCT *)`) are permitted.
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

### No Positional GROUP BY/ORDER BY (`no_positional_group_by_or_order_by`) [Auto-fixable]

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
  * `replacements`: A dictionary mapping search regex patterns (deprecated names) to target replacement suggestions (applied via `re.sub`).

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

### Metadata (`metadata`) [Partially Auto-fixable]

* **What it checks**:
  * Enforces model metadata documentation and testing:
    * **`owner`** [Auto-fixable]: Validates that the model config has a specified owner.
    * **`description`** [Auto-fixable]: Validates that the model description is defined and non-empty.
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

---

## 3. Health Scoring Configuration

TFF calculates an overall architecture health score (0–100) aggregated from all executed checks. By default, every check carries equal weight (`1.0`), and failures subtract penalties proportionally (an error penalty of `1.0` and warning penalty of `0.5` per affected model; or `100.0` error and `50.0` warning for project-level checks).

You can configure custom weights and failure penalties under the `health:` section in `fitness_functions.yaml`.

### Check and Category Weights

Assign custom relative weights to prioritize specific quality dimensions. Checks with higher weights have a greater influence on the overall score.

```yaml
health:
  weights:
    layer_integrity: 3.0       # Higher weight for critical architectural boundaries
    schema_contracts: 2.0
    column_names: 0.5           # Lower weight for naming conventions
    metadata: 1.5

  # Optionally set weights by connascence category
  category_weights:
    dynamic_coupling: 2.0       # Connascence of Timing / Execution
    static_coupling: 1.5        # Connascence of Position / Meaning
    naming: 0.75                # Connascence of Name
```

* **Check-level weights (`weights`)**: Map check or rule names (e.g. `layer_integrity`, `ban_select_star`) to a positive float weight.
* **Category weights (`category_weights`)**: Map categories (e.g. `connascence_of_algorithm`, `dynamic_coupling`, `metadata`) to a positive float weight. If both category and check weights are specified, check-level weights take precedence.

### Failure Penalties

Customize the penalty points deducted for errors and warnings:

```yaml
health:
  penalties:
    # Model-level penalties (deducted proportionally to model count)
    error: 1.0                  # Default: 1.0
    warning: 0.5                # Default: 0.5

    # Project-level penalties (subtracted directly from the check's 100-point score)
    project_error: 100.0        # Default: 100.0 (or decimal 1.0)
    project_warning: 50.0       # Default: 50.0 (or decimal 0.5)

    # Check-specific overrides
    checks:
      schema_contracts:
        error: 2.0              # Strict penalty for schema mismatch
      column_names:
        warning: 0.1            # Mild penalty for column name warnings
```

### Scoring Formula

1. **Model-Level Checks** (e.g. `ban_select_star`, `metadata`):
   $$\text{penalty points} = (\text{error count} \times \text{penalty}_{\text{error}}) + (\text{warning count} \times \text{penalty}_{\text{warning}})$$
   $$\text{score} = \max\left(0, 100 \times \left(1 - \frac{\text{penalty points}}{\text{penalty}_{\text{error}} \times \text{total models}}\right)\right)$$

2. **Project-Level Checks** (e.g. `layer_integrity`, `dependency_graph`):
   $$\text{score} = \max\left(0, 100 - (\text{error count} \times \text{penalty}_{\text{proj\_error}} + \text{warning count} \times \text{penalty}_{\text{proj\_warn}})\right)$$

3. **Overall Health Score**:
   The weighted average across all active checks:
   $$\text{Overall Score} = \frac{\sum (\text{score}_i \times \text{weight}_i)}{\sum \text{weight}_i}$$

