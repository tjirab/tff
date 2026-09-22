<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/tff-white.svg">
    <img alt="tff logo" src="docs/assets/tff.svg" width="160">
  </picture>
</p>

# tff

### Fast, zero-warehouse-cost architectural linter & health dashboard for dbt, SQLMesh & Dataform.
**Catch illegal upstream joins, layer violations, and duplicate transformation logic in CI.**

[![PyPI version](https://img.shields.io/pypi/v/tff-core.svg?logo=pypi)](https://pypi.org/project/tff-core/)
[![Python versions](https://img.shields.io/pypi/pyversions/tff-core.svg?logo=python)](https://pypi.org/project/tff-core/)
[![Documentation Status](https://readthedocs.org/projects/tff/badge/?version=latest)](https://tff.readthedocs.io/en/latest/?badge=latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

SQL linters check syntax and formatting in individual files, but they don't know your DAG. **tff** evaluates your transformation models holistically—enforcing layer boundaries, domain contracts, and logic deduplication across your entire data warehouse.

<p align="center">
  <img width="850" alt="tff catching layer violations and duplicate CTEs" src="docs/assets/demo-sqlmesh.gif" />
</p>

```text
$ tff check

╭──────────────────────────────── LINT FAILED ─────────────────────────────────╮
│  5 models checked  ·  3 errors  ·  4 warnings                                │
╰──────────────────────────────────────────────────────────────────────────────╯

Issues by Model
● marts/marketing/marketing_all_users.sql
  ✘ marts/marketing depends on sqlmesh_example.finance_stats (marts/finance)
    → Illegal cross-layer dependency! (layer_integrity)
  ⚠ CTE 'marketing_cleaned_users' duplicates transformation logic with 3 other models.
    → Connascence of Algorithm: extract into a shared upstream model. (duplicate_ctes)

● marts/finance/finance_stats.sql
  ⚠ CTE 'cleaned_users' duplicates transformation logic with 3 other models.
    → Connascence of Algorithm. (duplicate_ctes)

● core/users.sql
  ✘ SELECT * is prohibited. Explicitly name your columns to reduce coupling. (ban_select_star)
  ✘ Model owner should always be specified. (nomissingowner)

Lint failed — fix errors above before merging.
```

---

## ⚡ 30-Second Quickstart (Zero Config)

Run `tff` inside any existing dbt, SQLMesh, or Dataform repository. **No configuration file required**—`tff` automatically infers standard layer conventions (`staging` → `intermediate` → `core` → `marts`) and immediately audits your DAG:

```bash
# Instant zero-install invocation via uvx:
uvx --from "tff-core[dbt]" tff check        # for dbt
# uvx --from "tff-core[sqlmesh]" tff check  # for SQLMesh
# uvx --from "tff-core[dataform]" tff check # for Dataform

# Or install for your pipeline framework:
pip install "tff-core[dbt]"        # for dbt (or: uv add "tff-core[dbt]")
# pip install "tff-core[sqlmesh]"  # for SQLMesh
# pip install "tff-core[dataform]" # for Dataform

# Catch layer violations, duplicate CTEs, and circular dependencies
tff check

# Calculate your repository architecture health score (0–100)
tff health
```

---

## Why tff?

* 🛡️ **Layer Boundary Integrity**: Prevent dependency anti-patterns (e.g., marts querying raw staging directly or unauthorized cross-mart coupling).
* 🔍 **Duplicate CTE Detector**: Automatically detect duplicate complex CTEs across models (Connascence of Algorithm) and flag them for refactoring into upstream shared models.
* 📊 **Model Health Score**: Calculate objective repository health metrics (0–100) and enforce CI quality gates with `tff health --fail-under 80`.
* 🚦 **dbt, SQLMesh & Dataform CI Linter**: Built-in GitHub Action (`tjirab/tff@v1`) diffs PR changes against base branches, gates merges on health scores, and emits inline PR annotations.
* 🛠️ **Automated Fixers**: Auto-fix positional `GROUP BY`/`ORDER BY` clauses and scaffold missing metadata with `tff lint --fix`.
* 📐 **Multi-Engine Support**: First-class support for **dbt**, **SQLMesh**, and **Google Cloud Dataform**.

---

## 📖 Documentation

Full documentation, configuration guides, and cookbooks are available at [**tff.readthedocs.io**](https://tff.readthedocs.io/):

* 🚀 [**Getting Started & Integrations**](https://tff.readthedocs.io/) — Guides for [dbt](https://tff.readthedocs.io/en/latest/dbt/), [SQLMesh](https://tff.readthedocs.io/en/latest/sqlmesh/), and [Dataform](https://tff.readthedocs.io/en/latest/dataform/)
* 🔍 [**Rules & Checks Reference**](https://tff.readthedocs.io/en/latest/rules_and_checks/) — Complete catalog of architectural checks and linter rules
* 💻 [**CLI Reference Guide**](https://tff.readthedocs.io/en/latest/cli/) — Full list of CLI commands, options, and output formats (SARIF, JSON, HTML)
* 🤖 [**CI/CD & GitHub Actions**](https://tff.readthedocs.io/en/latest/ci_cd/) — Setting up automated PR governance with `tjirab/tff@v1` and pre-commit
* 🧩 [**Extending tff**](https://tff.readthedocs.io/en/latest/extending_tff/) — Writing custom rules, checks, and plugins
* 📊 [**GitLab Case Study**](https://tff.readthedocs.io/en/latest/case_study_gitlab/) — Auditing 2,200+ models in GitLab's open-source enterprise dbt repository

---

## License

Distributed under the [MIT License](LICENSE).
