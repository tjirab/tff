# Case Study: Auditing GitLab's 2,200-Model dbt Architecture

This case study documents a real-world architectural health audit conducted with **Transformation Fitness Functions (TFF)** against GitLab's enterprise data warehouse dbt project.

The goal of this audit was to evaluate how TFF's static analysis, connascence detection, and fitness rules perform on one of the largest and most mature open-source dbt repositories in the modern data ecosystem.

---

## 📌 Executive Summary

* **Target Project**: GitLab Data Team’s enterprise Snowflake dbt repository.
* **Scope**: 2,213 dbt models across 5 architectural layers.
* **Execution Time**: **~13 seconds** locally on a standard laptop.
* **Cost**: **$0.00** (Zero database connection required; zero Snowflake credits consumed).
* **Overall Project Health Score**: **76.3%** across 19 active fitness checks.
* **Primary Discoveries**:
  * **54 duplicated CTE algorithms** copied verbatim across up to 8 separate models.
  * **111 architectural layer integrity errors**, including reverse dependencies and cross-mart coupling.
  * Critical blast-radius hubs with up to **129 downstream dependents** (`dim_date`).
  * **1,409 models** (>63%) with `SELECT *` statements outside staging/source layers.

---

## 🏢 GitHub Source & Project Profile

### Source Repository
* **Repository**: [GitLab Data Team / analytics](https://gitlab.com/gitlab-data/analytics) (Public mirror / fork: [tconbeer/gitlab-analytics-sqlfmt](https://github.com/tconbeer/gitlab-analytics-sqlfmt))
* **Target Directory**: `transform/snowflake-dbt`
* **Target Engine / Dialect**: `dbt-core` with `dbt-snowflake`
* **Total Active Models**: 2,213 models

### Architectural Structure
GitLab organizes its models into an enterprise multi-tier hierarchy:
1. `models/sources`: Ingested raw source definitions and extracts.
2. `models/common_prep`: Low-level preparation and cleaning tables.
3. `models/common`: Dimensional models (`dim_*`) and normalized business facts (`fct_*`).
4. `models/marts`: Domain-specific business marts (`marts/marketing`, `marts/sales_funnel`, `marts/finance`, `marts/product`).
5. `models/workspaces`: Ad-hoc exploration and business-unit specific reporting.

---

## 🔬 Methodology

Traditional data warehouse linting solutions (such as `dbt-project-evaluator` packages) typically run dynamically inside the target cloud warehouse by compiling SQL into temporary views or tables. While functional, this approach requires live warehouse credentials, incurs cloud compute costs, and runs slowly on large repositories.

TFF adopts a **100% static analysis methodology**:

```mermaid
flowchart LR
    A["dbt parse / compile"] --> B["target/manifest.json"]
    B --> C["tff Engine"]
    D["fitness_functions.yaml"] --> C
    C --> E["AST Fingerprinting (CoA)"]
    C --> F["DAG Topology Analysis"]
    C --> G["Layer Boundary Checking"]
    C --> H["Syntactic Linter Checks"]
    E & F & G & H --> I["Health Report (76.3%)"]
    E & F & G & H --> J["Interactive HTML Lineage Dashboard"]
```

### 1. Zero-Credential Ingestion
The dbt project is compiled locally via `dbt parse` or `dbt compile`. TFF parses `target/manifest.json`, ingesting the dependency DAG, model definitions, SQL source, and test schemas into an in-memory normalized graph representation.

### 2. AST Fingerprinting (Connascence of Algorithm)
To detect duplicated logic across models without executing SQL:
* TFF parses SQL queries and Common Table Expressions (CTEs) into Abstract Syntax Trees (ASTs) using `sqlglot`.
* Query ASTs are normalized (stripping aliases and trivial formatting) and hashed.
* When CTE blocks with 12 or more AST nodes produce identical hashes in separate models, TFF flags them as **Connascence of Algorithm (CoA)** violations.

### 3. Topological Graph Traversal
TFF computes graph-theoretic properties across the 2,213 models:
* **Fan-Out (Blast Radius)**: The count of direct downstream dependents. Models with excessive fan-out represent single points of operational risk.
* **Fan-In (Coupling Sink)**: The count of direct upstream dependencies. Models with excessive fan-in represent bottleneck consolidators.

### 4. Layer & Domain Boundary Validation
Using the configured layer order (`sources` → `common_prep` → `common` → `marts` → `workspaces`):
* TFF inspects every edge in the dependency graph.
* Any edge pointing backwards (e.g. a model in `common_prep` querying a model in `common`) is flagged as a layer inversion error.
* Custom domain isolation boundaries flag horizontal cross-coupling between isolated marts.

---

## 📊 Audit Outcomes

### Overall Health Score: **76.3%**

```
╭───────────────────────── TFF PROJECT HEALTH REPORT ──────────────────────────╮
│                                                                              │
│  Overall Project Health Score: 76.3%                                         │
│  Models Checked: 2,213  ·  Active Checks: 19  ·  Categories: 8               │
│                                                                              │
╰──────────────────────────────────────────────────────────────────────────────╯

Health Score by Category
────────────────────────────────────────────────────────────────────────────────
Category                             Checks   Errors   Warnings    Score
────────────────────────────────────────────────────────────────────────────────
Connascence of Name (CoN)             4/6      1,470          ·    92.6%
Connascence of Type (CoT)             2/2          ·          ·   100.0%
Connascence of Position (CoP)         1/1         37          ·    98.5%
Connascence of Meaning (CoM)          1/1          ·          ·   100.0%
Connascence of Algorithm (CoA)        1/1          ·         54    98.8%
Connascence of Value (CoV)            1/1          ·      1,206    88.3%
Dynamic Coupling & DAG Structure      5/5        114         18    50.0%
Quality & Metadata                    4/7      3,451          ·    61.0%
────────────────────────────────────────────────────────────────────────────────
```

---

## 🔍 Key Architectural Discoveries

### 1. Duplicated Algorithms (Connascence of Algorithm — CoA)
TFF detected **54 duplicate CTE findings**, which cluster into **12 distinct duplicated algorithm groups** across the repository.

#### Precision in Nested Data Access (AST Parsing)
A common question when analyzing CTE duplication is whether static analysis can differentiate column projections in nested data (e.g. JSON variants in Snowflake). **TFF's AST engine distinguishes nested field access with high precision.**

For instance, comparing `bamboohr_custom_bonus_source.sql` and `engineering_development_team_members.sql`:
* In their final `renamed` CTEs, the models extract entirely different JSON elements (`data_by_row['id']::number` vs. `data_by_row['country']::varchar`). In SQLGlot, bracketed variant accesses compile into distinct `exp.Bracket` nodes with specific string literal identifiers. TFF computes distinct hashes for these and **never flags them as duplicates**.
* What TFF *did* flag was the upstream **JSON-flattening CTE** (`intermediate` in BambooHR vs. `flattened` in Engineering):
  ```sql
  -- Duplicated across 8 models (canonical AST matches identically despite alias differences):
  select d.value as data_by_row
  from source, lateral flatten(input => parse_json(jsontext), outer => true) d
  ```
Because TFF hashes the normalized query AST rather than outer CTE aliases, it caught that 8 separate models across People Analytics and Engineering shared the exact same 18-node unnesting algorithm.

---

#### Key Duplication Archetypes

##### Archetype A: PII Masking Algorithm Duplication (High Compliance Risk)
**Models involved (2)**: `zendesk_community_relations_users_source`, `zendesk_users_source`
```sql
-- Copied PII hashing algorithm:
select
    id as user_id,
    case
        when lower(email) like '%gitlab.com%' then name else md5(name)
    end as name,
    case
        when lower(email) like '%gitlab.com%' then email else md5(email)
    end as email,
    restricted_agent as is_restricted_agent,
    role,
    suspended as is_suspended,
    time_zone,
    created_at,
    ...
```
> **Architectural Risk**: When sensitive compliance logic (like PII masking) is copied between models rather than enforced via a macro, any future policy change (e.g., salting hashes or migrating from MD5 to SHA-256) risks partial rollout, exposing plain PII or creating mismatched customer IDs across systems.

##### Archetype B: Snapshot Deduplication Pattern (11 Models)
**Models involved (11)**: `categories_yaml_latest`, `feature_flags_yaml_latest`, `flaky_tests_latest`, `roles_yaml_latest`, `snowflake_grants_to_role`, `snowflake_grants_to_user`, `snowflake_show_roles`, `snowflake_show_users`, `stages_groups_yaml_latest`, `stages_yaml_latest`, `team_yaml_latest`.
```sql
-- Copied across 11 separate models:
select *
from source
where snapshot_date = (select max(snapshot_date) from source)
```
> **Architectural Risk**: 11 models maintain independent scalar subquery deduplications. Standardizing on dbt snapshots or a reusable snapshot filter macro eliminates boilerplate and improves query planner predictability.

##### Archetype C: Multi-Level Nested JSON Parsing (8 Models)
**Models involved (8)**: `accepted_solutions`, `daily_engaged_users`, `page_view_total_reqs`, `posts`, `signups`, `time_to_first_response`, `topics_with_no_response`, `visits`.
```sql
-- Identical 8-column double LATERAL FLATTEN copied across 8 models:
select
    json_value.value['start_date']::datetime as report_start_date,
    json_value.value['title']::varchar as report_title,
    json_value.value['type']::varchar as report_type,
    json_value.value['total']::varchar as report_total,
    data_level_one.value['x']::date as report_value_date,
    data_level_one.value['y']::int as report_value,
    uploaded_at as uploaded_at
from
    source,
    lateral flatten(input => parse_json(jsontext), outer => true) json_value,
    lateral flatten(json_value.value:data, '') data_level_one
```
> **Architectural Risk**: 8 separate Discourse source models run identical double `lateral flatten` table generators and data type conversions over raw JSON. An upstream `stg_discourse_reports` model would compute this once, reducing warehouse compute costs and eliminating schema drift risk.

##### Archetype D: Label Array Aggregation (2 Models)
**Models involved (2)**: `gitlab_dotcom_merge_requests_xf`, `gitlab_ops_merge_requests_xf`.
```sql
-- Complex label grouping with intra-group ordering:
select
    merge_requests.merge_request_id,
    array_agg(lower(masked_label_title)) within group (order by masked_label_title asc) as labels
from merge_requests
left join label_links on merge_requests.merge_request_id = label_links.target_id
left join all_labels on label_links.label_id = all_labels.label_id
group by merge_requests.merge_request_id
```

##### Archetype E: Deduplication via Window Function (2 Models)
**Models involved (2)**: `qualtrics_distribution_xf`, `qualtrics_survey_invitation_emails_sent`.
```sql
-- Window qualification deduplication:
select *
from {{ ref("qualtrics_distribution") }}
qualify row_number() over (partition by distribution_id order by uploaded_at desc) = 1
```

---

#### All 12 Duplication Clusters in GitLab's Codebase

| Cluster | Pattern / Sample CTE | Models Affected | Common Transformation Logic |
|---|:---|:---|:---|
| **1** | `max_select` | **11 models** | Snapshot filter: `snapshot_date = (select max(snapshot_date) from source)` |
| **2** | `parsed` (Discourse) | **8 models** | Double `lateral flatten` JSON unnesting & metric casting |
| **3** | `intermediate` (JSON flatten) | **8 models** | Single `lateral flatten(parse_json(jsontext))` |
| **4** | `intermediate` (Ranked YAML) | **6 models** | `lateral flatten` + `date_trunc('day', uploaded_at)` |
| **5** | `intermediate` (Flatten + upload) | **5 models** | `d.value as data_by_row, uploaded_at from lateral flatten` |
| **6** | `agg_labels` | **2 models** | MR `array_agg(lower(...)) within group` + label joins |
| **7** | `renamed` (PII Masking) | **2 models** | MD5 email/name hashing for non-`@gitlab.com` users |
| **8** | `qualtrics_distribution` | **2 models** | `qualify row_number() over (partition by distribution_id...) = 1` |
| **9** | `department_division_mapping` | **2 models** | `distinct department, division_mapped_current` |
| **10** | `renamed` (Projects) | **2 models** | Dotcom vs. Ops project source column mapping |
| **11** | `source` (YAML Rank) | **2 models** | `rank() over (partition by date_trunc('day', uploaded_at)...)` |
| **12** | `metric_per_row` | **2 models** | Array extraction for web vitals (blocking time & layout shift) |

> **Recommended Remediation**:
> 1. Centralize JSON flattening and PII hashing algorithms into reusable macros (e.g. `{{ flatten_json_source(...) }}`).
> 2. Create upstream intermediate models (e.g. `prep_discourse_reports.sql`, `prep_merge_request_labels.sql`) to avoid running heavy aggregations repeatedly in downstream models.


---

### 2. DAG Layer Integrity Violations
TFF caught **111 architectural layer violations** where data flow violated organizational boundaries:

#### A. Inverted Upstream Dependencies (Downstream Leaks)
Preparation models in `models/common_prep` were found directly referencing downstream presentation models in `models/common`:
* `prep_action` (`common_prep`) → depends on `dim_date` and `dim_namespace_plan_hist` (`common`).
* `prep_board` (`common_prep`) → depends on `dim_project` and `dim_date` (`common`).
* `prep_issue` (`common_prep`) → depends on `dim_project` and `dim_namespace_plan_hist` (`common`).

#### B. Cross-Mart Coupling
Models within one business domain mart were directly depending on internal models belonging to another domain mart:
* `mart_crm_attribution_touchpoint` (`marts/marketing`) directly depends on `mart_crm_opportunity` (`marts/sales_funnel`).

> **Architectural Impact**: Layer inversions create circular dependencies, break modular rebuilds, and make parallel orchestration difficult. Cross-mart coupling tightly binds independent business domains together.

---

### 3. Blast-Radius Hub Models & Bottlenecks
Using graph degree analysis, TFF identified high-risk architectural bottlenecks:

#### High Blast-Radius Hubs (Excessive Fan-Out)
A change to the schema or logic of these models triggers massive cascade rebuilds:
* `dim_date`: **129 downstream dependents** (`fan_out = 129`).
* `date_details`: **42 downstream dependents** (`fan_out = 42`).
* `dim_crm_account`: **39 downstream dependents** (`fan_out = 39`).

#### High-Coupling Sinks (Excessive Fan-In)
These models aggregate huge numbers of upstream dependencies:
* `gitlab_dotcom_tables_date`: **113 upstream models** (`fan_in = 113`).
* `pgp_snowflake_counts`: **105 upstream models** (`fan_in = 105`).

> **Architectural Impact**: `dim_date` is a critical single point of failure (blast radius of 129 models). High-sink models like `gitlab_dotcom_tables_date` become brittle build bottlenecks that fail whenever any of their 113 upstreams fail.

---

### 4. Code Quality & Governance Gaps

* **Coupling by Position (`CoP`)**:
  * **37 models** use positional column references (`GROUP BY 1, 2, 3`).
  * In `bamboohr_budget_vs_actual.sql`, TFF found **21 positional references** in a single statement.
* **`SELECT *` Proliferation**:
  * **1,409 models** (>63% of the repository) use `SELECT *` outside raw extraction layers, creating implicit coupling to upstream table schemas.
* **Testing & Documentation Coverage**:
  * **1,471 models** lack `unique` assertions on their primary keys.
  * **1,133 models** lack `not_null` assertions.
  * **757 models** have no description documented in schema YAML.

---

## 🛠️ Step-by-Step Reproduction Guide

To run this exact audit on GitLab's dbt project yourself:

### 1. Clone the GitLab Analytics Repository
```bash
git clone --depth 1 https://github.com/tconbeer/gitlab-analytics-sqlfmt.git gitlab-analytics
cd gitlab-analytics/transform/snowflake-dbt
```

### 2. Compile the Project Manifest
Generate the compiled `target/manifest.json` without needing database access:
```bash
uv run --with dbt-core --with dbt-snowflake dbt parse
```

### 3. Add `fitness_functions.yaml`
Create a `fitness_functions.yaml` in the `transform/snowflake-dbt` root:
```yaml
layers:
  order:
    - sources
    - common_prep
    - common
    - marts
    - workspaces

checks:
  layer_integrity:
    enabled: true
  dependency_graph:
    enabled: true
    fan_out_warn: 25
    fan_out_fail: 50
    fan_in_warn: 20
  duplicate_ctes:
    enabled: true
    severity: warning
    min_ast_nodes: 12

rules:
  ban_select_star:
    enabled: true
  no_positional_group_by_or_order_by:
    enabled: true
  metadata:
    owner: false
    description: true
    grain: false
    unique_values: true
    not_null: true
```

### 4. Execute TFF Commands
```bash
# Calculate overall architecture health score:
uvx tff-core health

# Inspect detailed violations grouped by connascence category:
uvx tff-core lint --group-by connascence

# Generate standalone interactive HTML documentation and lineage graph:
uvx tff-core docs --output gitlab_tff_report.html
```

---

## 💡 Lessons for Data Platform Engineers

1. **Static Analysis is 100x Faster than Dynamic Evaluation**:
   Evaluating 2,213 models in Snowflake with SQL queries takes minutes to hours and consumes warehouse credits. TFF completed the entire evaluation in **13 seconds** on developer hardware.
2. **Duplicated Algorithms Silently Spread**:
   Without AST-level fingerprinting, copy-pasting complex CTEs across models goes unnoticed in peer code reviews until business metrics diverge.
3. **Fitness Functions Belong in CI/CD**:
   Running `tff health --fail-under 80` or `tff lint` in GitHub Actions / GitLab CI prevents layer inversions and blast-radius bottlenecks from entering `main`.
