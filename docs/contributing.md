# Contributor & Architecture Guide

Welcome! This document outlines the codebase architecture, package layout, and local development environment setup for tff (Transformation Fitness Functions).

---

## High-Level Architecture

tff is structured to separate the core, adapter-agnostic logic of parsing and checking rules from any specific data orchestrator or engine.

```mermaid
flowchart TD
    subgraph CLI ["CLI & Orchestration"]
        TFF_CLI["Unified tff CLI<br/>(Provider Auto-Detection)"]
        Legacy_CLI["tff-dbt / tff-sqlmesh / tff-dataform"]
        Config["fitness_functions.yaml<br/>(FitnessFunctionsConfig)"]
    end

    subgraph Adapters ["Pipeline Adapters (tff.core.adapter.PipelineAdapter)"]
        direction TB
        subgraph DBT_Box ["dbt Adapter (tff.dbt)"]
            DBT_Ad["DBTAdapter"]
            DBT_Parser["Manifest Parser<br/>(manifest.json & tests)"]
            DBT_Ad --> DBT_Parser
        end

        subgraph SM_Box ["SQLMesh Adapter (tff.sqlmesh)"]
            SM_Ad["SqlmeshAdapter"]
            SM_Loader["FitnessLoader<br/>(Dynamic SqlMeshRule wrapper)"]
            SM_Ad --> SM_Loader
        end

        subgraph DF_Box ["Dataform Adapter (tff.dataform)"]
            DF_Ad["DataformAdapter"]
            DF_Parser["Manifest & AST Parser<br/>(JSON manifest / CLI / .sqlx)"]
            DF_Ad --> DF_Parser
        end
    end

    subgraph Core ["tff.core Engine"]
        Model["ModelRepresentation<br/>(AST, columns, audits, depends_on)"]
        Rules["Single-Model Rules<br/>(Naming, contracts, docs, types)"]
        Checks["Architectural DAG Checks<br/>(Layer integrity, cycles, depth, CTEs)"]
    end

    subgraph Outputs ["Outputs & Actions"]
        Reporter["Rich Lint Reporter<br/>(Console, JSON, SARIF, Markdown)"]
        Autofix["Autofix Engine<br/>(AST & YAML schema auto-mutations)"]
    end

    TFF_CLI --> Adapters
    Legacy_CLI --> Adapters
    Config -.-> Rules
    Config -.-> Checks

    DBT_Parser -->|"Maps nodes & tests"| Model
    SM_Loader -->|"Maps models & audits"| Model
    DF_Parser -->|"Maps actions & .sqlx"| Model

    Model --> Rules
    Model --> Checks

    Rules --> Reporter
    Checks --> Reporter
    Rules --> Autofix
    Checks --> Autofix
```

### Core Architecture Components
1. **[tff-core](https://github.com/tjirab/tff/tree/main/packages/tff-core)**: Contains the base model definitions (`ModelRepresentation`), abstract rule and check classes, the built-in rules/checks, the unified `tff` CLI entry point, configuration loader (`fitness_functions.yaml`), reporting engine, and the autofix engine. It also defines the abstract `PipelineAdapter` interface.
2. **dbt Adapter (`tff.dbt`)**: Implements `DBTAdapter`. Parses compile-time artifacts (`manifest.json`) and resolves references, schemas, and tests, mapping them into `ModelRepresentation` objects.
3. **SQLMesh Adapter (`tff.sqlmesh`)**: Implements `SqlmeshAdapter`. Connects directly to SQLMesh contexts, mapping native SQLMesh models into `ModelRepresentation` objects. It also provides `FitnessLoader` to dynamically wrap core rules into native `SqlMeshRule` classes for SQLMesh's built-in linter and CI workflows.
4. **Dataform Adapter (`tff.dataform`)**: Implements `DataformAdapter`. Ingests Google Cloud Dataform projects via precompiled JSON manifests, CLI compilation (`dataform compile --json`), or direct static `.sqlx` AST parsing.
5. **Custom Extensions & Adapters**: See the [Extending tff Guide](extending_tff.md) for how to implement proprietary rules, architectural DAG checks, and pipeline adapters.


---

## Monorepo Layout

```
├── pyproject.toml              # Root workspace settings
├── release-please-config.json  # Release Please configurations
├── packages/
│   ├── tff-core/               # Unified codebase (core, dbt, sqlmesh)
│   └── sqlmesh-ff/             # Deprecated backward compatibility wrapper
```

---

## Local Development Setup

We use **`uv`** to manage local workspaces, virtual environments, and dependencies.

### 1. Initialize Workspace
Clone the repo and sync the project dependencies in editable mode:
```bash
uv sync --all-extras
```

### 2. Run Tests
Execute the entire workspace test suite using `pytest`:
```bash
uv run pytest
```

### 3. Coverage & Linting
Verify test coverage and run lint rules:
```bash
# Run tests and generate coverage report:
uv run pytest --cov=packages --cov-report=xml

# Check diff coverage against main branch (100% required in PRs):
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=100

# Run linting check:
uv run ruff check .
```

### 4. Performance Benchmarks & Corpus Verification
Ensure changes do not cause performance regressions or false positives:
```bash
# Run performance benchmark against SLA ceiling (default 15.0s):
uv run python scripts/benchmark.py --max-seconds 15.0

# Run corpus snapshot regression tests:
uv run pytest packages/tff-core/tests/test_corpus_snapshots.py
```

---

## Strategic Guardrails & Product Boundaries

To keep `tff` focused and reliable as it evolves, all contributions must adhere to our product constitution:

### 1. Core Focus vs. Anti-Goals
* **What tff IS**: A compile-time DAG architecture, coupling, and modularity fitness tool. It enforces layer boundaries, Connascence of Algorithm (duplicate transformation CTEs), domain ownership, and schema contracts.
* **What tff is NOT**:
  * **Not a syntax or formatting linter**: Formatting, trailing commas, and keyword case belong to [SQLFluff](https://sqlfluff.com/) or [Ruff](https://astral.sh/ruff).
  * **Not a runtime data assertion engine**: Row counts, null checks on live tables, and distribution assertions belong to dbt tests, Great Expectations, or Soda.
  * **Not an orchestrator**: Pipeline scheduling and execution belongs to Airflow, Dagster, or Cosmos.

### 2. Zero-Config First Run
Any valid dbt, SQLMesh, or Dataform project must yield valuable insights out of the box with `tff check` without requiring manual configuration files. Smart defaults and automatic layer inference (`staging` → `intermediate` → `core` → `marts`) must always work.

### 3. Actionability Over Identification
Checks must never produce vague warnings. Every violation should include actionable remediation instructions (e.g., target layer recommendations, CTE deduplication guidance, or automated fixes via `tff autofix`).

---

## Rule Lifecycle & Acceptance Checklist

To avoid user alert fatigue and maintain confidence across CI pipelines, rules progress through three lifecycle stages:

```mermaid
stateDiagram-v2
    [*] --> Experimental: New rule submitted
    Experimental --> Stable: Validated on corpus benchmarks
    Stable --> Deprecated: Superseded by new check
    Deprecated --> [*]: Removed after 2 minor releases
```

* **`experimental`**: Opt-in or non-blocking (`severity="warning"`). Gathers feedback from real-world repositories without breaking existing CI merge gates.
* **`stable`**: Standard default suite. Covered by strict semantic versioning; rule IDs and diagnostic formats are immutable without deprecation windows.
* **`deprecated`**: Flagged for removal, accompanied by clear migration paths in release notes and CLI messages.

### Pull Request Checklist for New Rules / Checks
Before submitting a new rule or check:
- [ ] **Architectural Justification**: Does it target DAG coupling, layer violations, or logic duplication?
- [ ] **False-Positive Ceiling**: Does it exhibit `< 1%` false positives on our corpus benchmark fixtures (`examples/minimal-*` and real-world projects)?
- [ ] **Engine Parity**: Does it run consistently across dbt, SQLMesh, and Dataform via `tff.core.adapter.PipelineAdapter`?
- [ ] **Actionable Remediation**: Does the error message or `--explain` provide concrete guidance or an autofix?
- [ ] **Coverage**: 100% diff test coverage verified via `diff-cover`.

---

## Releases & PR Titles

Releases are managed by Google's `release-please` action. 

Your PR titles **must** use the [Conventional Commits](https://www.conventionalcommits.org/) format so that minor/patch versions are calculated correctly:
* `feat: ...` (bumps minor version, e.g., `0.2.0` $\rightarrow$ `0.3.0`)
* `fix: ...` (bumps patch version, e.g., `0.2.0` $\rightarrow$ `0.2.1`)
* `chore: ...`, `docs: ...`, `test: ...` (non-bumping metadata changes)
