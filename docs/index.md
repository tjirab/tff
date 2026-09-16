<p align="center">
  <img src="assets/tff.svg#only-light" alt="TFF Logo" width="160">
  <img src="assets/tff-white.svg#only-dark" alt="TFF Logo" width="160">
</p>

# TFF: Transformation Fitness Functions

[![PyPI version](https://img.shields.io/pypi/v/tff-core.svg?logo=pypi)](https://pypi.org/project/tff-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/tff-core.svg?logo=python)](https://pypi.org/project/tff-core/)
[![Documentation Status](https://readthedocs.org/projects/tff/badge/?version=latest)](https://tff.readthedocs.io/en/latest/?badge=latest)

Configurable fitness functions engine and linter for transformation projects.

**TFF** allows you to enforce architectural layout boundaries, layer structure policies, schema contracts, and code formatting rules across data pipelines. It ships with dedicated plugins for **SQLMesh**, **dbt**, and **Google Cloud Dataform**, supports custom adapters and proprietary rules via entry points and plugins, and outputs clean, color-coded lint reports to the terminal.

---

## Key Capabilities

* **Multi-Engine Support**: Native integration with [SQLMesh](sqlmesh.md), [dbt](dbt.md), and [Google Cloud Dataform](dataform.md).
* **Architectural Boundaries**: Prevent dependency anti-patterns (e.g., marts querying staging or raw source tables).
* **Automated Linting & Autofix**: Check SQL dialects, column naming conventions, ban `SELECT *`, and auto-fix formatting issues.
* **Health Scoring**: Calculate objective repository health metrics (0–100) and enforce CI quality gates with `--fail-under`.
* **CI/CD Quality Gates**: Built-in GitHub Action runner diffing PR changes against base branches (`main`).
* **Extensible Architecture**: Write custom rules and adapters via [Python API](api/rules.md).

---

## Quick Installation

Install the package with the adapter matching your pipeline tool:

=== "SQLMesh"

    ```bash
    # With uv:
    uv add "tff-core[sqlmesh]"

    # With pip:
    pip install "tff-core[sqlmesh]"
    ```

=== "dbt"

    ```bash
    # With uv:
    uv add "tff-core[dbt]"

    # With pip:
    pip install "tff-core[dbt]"
    ```

=== "Dataform"

    ```bash
    # With uv:
    uv add "tff-core[dataform]"

    # With pip:
    pip install "tff-core[dataform]"
    ```

---

## Quick CLI Usage

Once installed, use the unified `tff` CLI to run linting, calculate health scores, and enforce architectural quality gates:

```bash
# Run architectural fitness checks and linting
tff lint

# Automatically fix simple linting violations
tff lint --fix

# Calculate overall repository health score and enforce quality gate
tff health --fail-under 80

# View detailed environment, adapter, and rule info
tff info
```

For full CLI options and flags, see the [CLI Reference](cli.md).

---

## Documentation Navigation

* 📐 [SQLMesh Integration Guide](sqlmesh.md)
* ⚡ [dbt Integration Guide](dbt.md)
* ☁️ [Dataform Integration Guide](dataform.md)
* 💻 [CLI Reference Guide](cli.md)
* 🔍 [Rules & Checks Reference](rules_and_checks.md)
* 🤖 [CI/CD & GitHub Actions Guide](ci_cd.md)
* 📊 [Case Study: GitLab dbt Audit (2,200+ models)](case_study_gitlab.md)
* 🔌 [API Reference - Adapters](api/adapters.md)
* 📜 [API Reference - Rules](api/rules.md)
* 🏗️ [Architecture & Contributor Guide](contributing.md)
