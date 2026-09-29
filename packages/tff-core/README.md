# tff-core

Core architectural linter and fitness function engine for data transformation pipelines.

`tff-core` executes layer boundary validation, structural graph policies, schema contracts, and duplicate logic detection across dbt, SQLMesh, and Google Cloud Dataform projects.

## Installation

Install `tff-core` with the adapter corresponding to your transformation engine:

```bash
# dbt adapter
pip install "tff-core[dbt]"

# SQLMesh adapter
pip install "tff-core[sqlmesh]"

# Dataform adapter
pip install "tff-core[dataform]"

# All adapters
pip install "tff-core[all]"
```

## Architecture

| Subsystem | Function & Scope |
| :--- | :--- |
| **AST & Semantic Parser** | Extracts AST nodes and semantic relationships using SQLGlot without database connections. |
| **Check Registry** | Unified execution harness evaluating layer integrity, syntax bans, and duplicate CTEs. |
| **Health Scoring** | Computes weighted quality metrics (0–100) and penalty distributions. |
| **Adapter Interface** | Normalizes project manifests and configurations across pipeline engines. |

## Documentation

For CLI usage, configuration specifications, and rule authoring, refer to the [main documentation](https://tff.readthedocs.io/) and the [tff repository](https://github.com/tjirab/tff).

## License

Distributed under the [MIT License](https://github.com/tjirab/tff/blob/main/LICENSE).
