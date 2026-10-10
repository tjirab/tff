# ADR-0001: Monorepo and Provider Adapter Pattern

- **Status**: Accepted
- **Deciders**: `tff` Core Maintainers
- **Date**: 2026-10-10

---

## Context and Problem Statement

Modern analytics engineering teams use diverse SQL orchestration frameworks, primarily **dbt**, **SQLMesh**, and **Google Cloud Dataform**. Each framework maintains distinct manifest representations, project configurations, and metadata schemas:
- `dbt` uses `manifest.json` and Jinja-templated SQL files.
- `SQLMesh` uses Python- or SQL-based model definitions with native macro evaluation.
- `Dataform` uses `dataform.json` and SQLX definitions with JavaScript blocks.

Building separate standalone fitness function tools for each framework would fragment governance rules, duplicate AST analysis logic, and degrade user experience across heterogeneous data stacks. Conversely, tightly coupling framework SDKs directly into a single monolith could introduce heavy, conflicting dependencies (e.g. `sqlmesh` vs `dbt-core` protobuf or dependency pins).

How should `tff` structure its codebase and engine integrations to deliver unified architectural linting while isolating engine dependencies?

---

## Decision Drivers

- **Dialect and Engine Agnosticism**: Unified rule engine (`tff-core`) evaluating model DAGs independently of the underlying orchestration engine.
- **Dependency Isolation**: Preventing framework dependencies (like SQLMesh or dbt) from bloating minimal installations or creating mutually incompatible dependency trees.
- **Extensibility**: Enabling third-party or proprietary framework adapters without modifying core logic.
- **Maintenance Ergonomics**: Single development lifecycle and synchronized versioning for core governance rules.

---

## Considered Options

1. **Monorepo with Core + Optional Engine Packages**: A centralized repository containing `packages/tff-core` (the CLI and base adapters) and companion packages like `packages/sqlmesh-ff`.
2. **Monolithic Single Package with Heavy Dependencies**: A single Python package bundling `dbt-core`, `sqlmesh`, and Google Cloud libraries as direct mandatory dependencies.
3. **Polyrepo Architecture**: Completely decoupled Git repositories for each tool (`tff-core`, `tff-dbt`, `tff-sqlmesh`, `tff-dataform`).

---

## Decision Outcome

Chosen option: **Option 1: Monorepo with Core + Optional Engine Packages**, utilizing an abstract `PipelineAdapter` contract and dynamic provider discovery.

### Positive Consequences

- `tff-core` maintains a lightweight footprint relying primarily on `sqlglot`, `pydantic`, `networkx`, and `click`.
- Framework integrations implement a uniform interface (`PipelineAdapter`), standardizing model extraction into `ModelRepresentation` objects.
- Adapters can be loaded via dynamic entry points or lazy imports (`register_adapter`), eliminating hard dependency conflicts.
- Developers can test end-to-end multi-engine workflows in a single workspace.

### Negative Consequences & Trade-offs

- Workspace setup requires toolchains capable of multi-package development (standardized on `uv` workspaces).
- Provider-specific test suites require careful isolation to avoid running optional adapter tests when dependencies are absent.

---

## Pros and Cons of Options

### Option 1: Monorepo with Core + Optional Engine Packages

- Positive: Clear separation of concerns; zero dependency contamination; shared rule engine test suites.
- Positive: Single PR can enhance both core AST rules and framework-specific adapter bindings.
- Negative: Requires monorepo build configuration (`pyproject.toml` workspace).

### Option 2: Monolithic Single Package

- Positive: Simple single-package distribution.
- Negative: High risk of dependency version collisions between engine packages (e.g. conflicting `pydantic` or `rich` versions).
- Negative: Unacceptable install size and overhead for users only needing lightweight dbt or Dataform linting.

### Option 3: Polyrepo Architecture

- Positive: Completely isolated git histories and release cycles.
- Negative: Severe maintenance overhead synchronizing breaking changes across 4+ repositories.
- Negative: Friction for community contributions requiring coordinated multi-repo pull requests.

---

## Technical Details & Architecture Notes

- Adapters derive from `tff.core.adapter.PipelineAdapter`.
- Standard contract methods:
  - `is_applicable(project_root: Path) -> bool`
  - `load_models(project_root: Path | Sequence[Path], dialect: str | None, manifest_path: Path | None) -> dict[str, ModelRepresentation]`
  - `run_checks(...) -> tuple[list[LintFinding], int, list[str]]`
- Model metadata is normalized into immutable dataclasses/Pydantic schemas with standardized fields (`name`, `path`, `layer`, `depends_on`, `raw_sql`, `ast`).
