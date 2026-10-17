# ADR-0003: Layer Inference and Hierarchy Conventions

- **Status**: Accepted
- **Deciders**: `tff` Core Maintainers
- **Date**: 2026-10-10

---

## Context and Problem Statement

A core capability of `tff` is enforcing architectural boundaries and DAG governance (e.g. preventing illegal upstream joins, layer bypassing, or circular dependencies). In analytics engineering, data warehouses are partitioned into conceptual layers such as staging, intermediate, core, and marts.

However, data repositories vary widely in how models declare layer membership:
1. Some repositories organize models strictly by folder path (e.g. `models/staging/`, `definitions/intermediate/`).
2. Some repositories declare layer names via model naming prefixes (e.g. `stg_orders`, `int_customers`, `fct_sales`).
3. Some frameworks support metadata tags or configuration blocks (e.g. `config(tags=['layer:marts'])`).

Without a formal, deterministic inference order and configurable fallback convention, models can be misclassified, leading to false-positive violations or silent rule escapes.

---

## Decision Drivers

- **Zero-Config Usability**: Immediate out-of-the-box layer detection on standard dbt/SQLMesh/Dataform conventions without mandatory config files.
- **Configurability**: Explicit user-defined layers and layer order in `fitness_functions.yaml` must take precedence over heuristic defaults.
- **Predictability & Traceability**: Clear precedence rules so developers understand why a model was assigned to a given layer.
- **Extensibility**: Support custom layer names (e.g., `raw`, `base`, `cleansed`, `analytics`) beyond default naming schemes.

---

## Considered Options

1. **Multi-Strategy Precedence with Sensible Default Order**:
   - Order: Explicit model config/tags -> Directory path hierarchy -> Model naming prefix -> Unclassified fallback.
   - Configurable `layers.order` with standard default (`staging -> intermediate -> core -> marts`).
2. **Path-Only Mapping**:
   - Classify layers exclusively based on directory paths.
3. **Prefix-Only Mapping**:
   - Classify layers exclusively based on model prefixes (`stg_`, `int_`, `fct_`, `dim_`).

---

## Decision Outcome

Chosen option: **Option 1: Multi-Strategy Precedence with Sensible Default Order**.

### Positive Consequences

- Works out-of-the-box on convention-adhering repositories even if `fitness_functions.yaml` is not yet created.
- Teams with specialized directory layouts or naming schemes can customize `layers.order` and regex mappings in configuration.
- Supports both standard dbt layer terminology (`staging`, `intermediate`, `marts`) and classic warehouse nomenclature (`staging`, `core`, `marts`).
- DAG checks can verify unidirectional data flow across ordered layers (`upstream -> downstream`).

### Negative Consequences & Trade-offs

- Heuristic inference could misclassify models if ambiguous folder names collide with layer names. This is mitigated by allowing explicit override tags and strict config definitions.

---

## Pros and Cons of Options

### Option 1: Multi-Strategy Precedence with Sensible Default Order

- Positive: Maximum compatibility with real-world heterogeneous codebases; smooth onboarding experience.
- Positive: Clear deterministic fallback hierarchy.
- Negative: Slightly more complex resolver logic.

### Option 2: Path-Only Mapping

- Positive: Simple to implement.
- Negative: Breaks projects that organize models by domain first (e.g. `models/finance/stg_invoices.sql`) rather than layer first.

### Option 3: Prefix-Only Mapping

- Positive: Simple regex lookup.
- Negative: Fails in teams that do not enforce strict Hungarian-notation model prefixes.

---

## Technical Details & Architecture Notes

- Default layer hierarchy:
  `["staging", "intermediate", "core", "marts"]`
- In `tff.core.config.FitnessFunctionsConfig`:
  - `layers.order`: Sequence of layer strings ordered from most upstream to most downstream.
  - Directional validation ensures that edges in the DAG $(u \to v)$ only flow from upstream layers to downstream layers (or within the same allowed layer domain).
- Unclassified models are handled gracefully or reported with diagnostics rather than crashing the evaluation pipeline.
