# Contributor & Architecture Guide

Welcome! This document outlines the codebase architecture, package layout, and local development environment setup for TFF (Transformation Fitness Functions).

---

## High-Level Architecture

TFF is structured to separate the core, adapter-agnostic logic of parsing and checking rules from any specific data orchestrator or engine.

```mermaid
graph TD
    subgraph Core Engine [tff-core]
        Model[ModelRepresentation]
        Rules[Linter Rules]
        Checks[Architectural Checks]
        Report[Rich Lint Reporter]
    end

    subgraph SQLMesh Adapter [tff-sqlmesh]
        SM_Loader[FitnessLoader] -->|Wraps via type()| Rules
        SM_Runner[Runner] -->|Maps SQLMesh Model| Model
        SM_CLI[tff-sqlmesh CLI] --> SM_Runner
    end

    subgraph dbt Adapter [tff-dbt]
        DBT_Manifest[Manifest Parser] -->|Maps nodes & tests| Model
        DBT_Runner[Runner] --> DBT_Manifest
        DBT_CLI[tff-dbt CLI] --> DBT_Runner
    end
    
    Model --> Rules
    Model --> Checks
    Rules --> Report
    Checks --> Report
```

### Core Architecture Components
1. **[tff-core](file:///Users/bartschuijt/git/sqlmesh-ff/packages/tff-core)**: Contains the base model definitions (`ModelRepresentation`), abstract rule classes, the 13 built-in rules/checks, and the console rendering engine using `rich`. It has **no dependency** on SQLMesh or dbt.
2. **[tff-sqlmesh](file:///Users/bartschuijt/git/sqlmesh-ff/packages/tff-sqlmesh)**: Plugs directly into SQLMesh. It maps native SQLMesh models into `ModelRepresentation` objects and wraps core rules dynamically using Python's `type()` constructor.
3. **[tff-dbt](file:///Users/bartschuijt/git/sqlmesh-ff/packages/tff-dbt)**: Parsers compile-time artifacts (`manifest.json`) and resolves references, schemas, and tests, running core rules on the compiled model layout.

---

## Monorepo Layout

```
├── pyproject.toml              # Root workspace settings
├── release-please-config.json  # Release Please configurations
├── packages/
│   ├── tff-core/               # Shared logic & engine
│   ├── tff-sqlmesh/            # SQLMesh loader, runner, & CLI
│   ├── tff-dbt/                # dbt parser, runner, & CLI
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

---

## Releases & PR Titles

Reases are managed by Google's `release-please` action. 

Your PR titles **must** use the [Conventional Commits](https://www.conventionalcommits.org/) format so that minor/patch versions are calculated correctly:
* `feat: ...` (bumps minor version, e.g., `0.2.0` $\rightarrow$ `0.3.0`)
* `fix: ...` (bumps patch version, e.g., `0.2.0` $\rightarrow$ `0.2.1`)
* `chore: ...`, `docs: ...`, `test: ...` (non-bumping metadata changes)
