# CI/CD Integration & Official GitHub Action Guide

This guide covers integrating **Transformation Fitness Functions (TFF)** into automated CI/CD pipelines, including the official **GitHub Action**, pre-commit hooks, and alternative CI systems (GitLab CI, Azure DevOps, Bitbucket, and SARIF code scanning).

---

## 1. Official GitHub Action (`tjirab/tff@v1`)

The official TFF GitHub Action allows teams to enforce architectural fitness functions and project health scores directly on pull requests with zero manual virtualenv configuration.

### Quick Start Workflow

Create `.github/workflows/tff.yml` in your repository:

```yaml
name: TFF Architectural Fitness Functions

on:
  pull_request:
    branches: [ main ]

jobs:
  tff-check:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write  # Required for posting/updating PR summary comments
    steps:
      - name: Checkout Code
        uses: actions/checkout@v4
        with:
          fetch-depth: 0  # Required to compute health score diff vs base branch

      - name: Run TFF Action
        uses: tjirab/tff@v1
        with:
          project: "."
          provider: "auto"
          fail-under: "80.0"
          fail-level: "error"
          comment-pr: "true"
```

---

### Action Configuration Reference

#### Inputs

| Input | Description | Default | Required |
| :--- | :--- | :--- | :--- |
| `project` | Path to project root directory | `.` | No |
| `provider` | Pipeline engine (`auto`, `dbt`, `sqlmesh`, `dataform`) | `auto` | No |
| `fail-under` | Minimum overall health score required to pass (`0.0` - `100.0`) | `0.0` | No |
| `fail-level` | Severity level that triggers step failure (`error`, `warning`) | `error` | No |
| `only-changed` | Only gate and report violations for files/models modified in this PR | `false` | No |
| `comment-pr` | Post or update interactive PR summary comment with score and violations | `false` | No |
| `github-token` | GitHub token for creating/updating PR comments | `${{ github.token }}` | No |
| `config` | Path to `fitness_functions.yaml` (relative to project root) | `fitness_functions.yaml` | No |
| `checks` | Comma-separated list of specific checks to run | (all enabled) | No |
| `python-version` | Python version to set up in the runner | `3.12` | No |
| `version` | Specific version of `tff-core` to install | (latest release) | No |
| `annotations` | Emit GitHub Actions workflow annotations (`::error` / `::warning`) | `true` | No |
| `diff-against-base` | Compute health score diff and violations diff vs target branch | `true` | No |

#### Outputs

| Output | Description | Example |
| :--- | :--- | :--- |
| `health-score` | Overall project fitness health score (`0.0` - `100.0`) | `94.5` |
| `violations-count` | Total number of violations found in evaluated scope | `3` |
| `errors-count` | Total number of errors found | `1` |
| `warnings-count` | Total number of warnings found | `2` |
| `passed` | Whether all checks passed according to thresholds (`true`/`false`) | `true` |
| `comment-id` | GitHub PR comment ID if a comment was created or updated | `18492048` |

---

### Gating Modes: Full Project vs. Modified Files Only

#### Mode 1: Full Project Gating (Default)
Evaluates the entire repository against your architectural rules. Ideal for greenfield repositories or projects with high baseline quality:

```yaml
- uses: tjirab/tff@v1
  with:
    fail-under: "85.0"
    fail-level: "error"
```

#### Mode 2: Modified Files Only (`only-changed: true`)
In large existing projects with legacy technical debt, teams often want **strict modified-files gating**:
* Developers are **only evaluated on and blocked by the models they touched** in their pull request.
* Pre-existing violations in untouched legacy models will not block PR merges.

```yaml
- uses: tjirab/tff@v1
  with:
    fail-under: "80.0"
    fail-level: "error"
    only-changed: "true"   # 👈 Evaluates & gates only models touched in this PR
    comment-pr: "true"
```

Under the hood:
1. TFF determines modified `.sql` and `.yml` files using `git diff --name-only origin/${base_ref}...HEAD`.
2. Cross-model dependencies and schemas are still loaded to properly validate DAG boundaries (like layer integrity and schema contracts).
3. Violations, annotations, and pass/fail exit codes are filtered strictly to the modified files.
4. The PR comment explicitly displays:
   ```markdown
   > **Mode**: 🔍 Gating 3 modified file(s) in PR · Minimum score: 80.0% · Severity threshold: error
   > ℹ️ *4 pre-existing violation(s) in unmodified files were excluded due to only-changed: true.*
   ```

---

### PR Comment & Annotation Features

#### 1. Interactive PR Summary Comment
When `comment-pr: "true"` is enabled:
* **Overall Metrics**: Health score, pass/fail status badge, violation counts.
* **Score Delta**: Displays progress against target branch (`+2.5% vs main 📈` or `-1.0% vs main 📉`).
* **Violation Diffs**: Explicitly distinguishes **New Violations Introduced** from **Resolved Violations**.
* **Category Breakdown**: Displays health score percentages across Connascence categories.
* **Idempotent Updates**: Automatically edits the existing comment on new commits to avoid comment clutter.

#### 2. In-File Inline Annotations ("Files changed" Tab)
When `annotations: "true"` (default):
* TFF emits native GitHub workflow commands (`::error` and `::warning`).
* GitHub renders findings directly inline on the modified lines of code in the **Files changed** tab.
* Developers can jump directly to violations in the diff without leaving their code review flow.

#### 3. GitHub Actions Job Summary
The complete Markdown health report is automatically published to the GitHub Actions **Job Summary** page on every workflow run.

---

### Monorepo & Multi-Project Matrix Setups

For repositories containing multiple transformation projects (e.g., separate dbt and Dataform projects):

```yaml
jobs:
  tff-matrix:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        include:
          - project: "analytics/dbt"
            provider: "dbt"
          - project: "marketing/dataform"
            provider: "dataform"
    permissions:
      contents: read
      pull-requests: write
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: tjirab/tff@v1
        with:
          project: ${{ matrix.project }}
          provider: ${{ matrix.provider }}
          fail-under: "80.0"
          comment-pr: "true"
```

---

## 2. Pre-commit Hooks Integration

TFF includes native pre-commit hook manifests (`.pre-commit-hooks.yaml`) to validate and auto-fix violations locally before commits are created.

Add to your `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/tjirab/tff
    rev: v0.12.1
    hooks:
      # Architectural and code formatting linter
      - id: tff-lint

      # Optional: automatically fix simple violations (positional GROUP BY, metadata scaffolds)
      # - id: tff-lint-fix
```

### Declaring Adapter Dependencies

The pre-commit hooks default to bare `tff-core`, which supports **dbt** and **Dataform** out of the box.

For **SQLMesh** projects, declare `additional_dependencies: ["tff-core[sqlmesh]"]`:

```yaml
  - repo: https://github.com/tjirab/tff
    rev: v0.12.1
    hooks:
      - id: tff-lint
        additional_dependencies: ["tff-core[sqlmesh]"]
```

---

## 3. Other CI Systems

### GitLab CI (JUnit XML Test Tab)

GitLab CI natively parses JUnit XML test reports into a rich **Tests** tab on merge requests:

```yaml
# .gitlab-ci.yml
stages:
  - test

tff_fitness_functions:
  stage: test
  image: python:3.12
  script:
    - pip install "tff-core[dbt]"
    - tff lint --junit-xml reports/junit.xml
    - tff health --fail-under 80.0
  artifacts:
    when: always
    reports:
      junit: reports/junit.xml
```

### GitHub Advanced Security & Code Scanning (SARIF v2.1.0)

Export OASIS SARIF v2.1.0 reports directly into GitHub Code Scanning:

```yaml
# .github/workflows/codeql.yml
steps:
  - uses: actions/checkout@v4
  - uses: actions/setup-python@v5
    with:
      python-version: '3.12'

  - run: |
      pip install "tff-core[dbt]"
      tff lint --format sarif > tff-results.sarif

  - uses: github/codeql-action/upload-sarif@v3
    if: always()
    with:
      sarif_file: tff-results.sarif
```

---

## 4. CLI CI Commands Quick Reference

| Command | Purpose |
| :--- | :--- |
| `tff action [options]` | Run composite action pipeline (health scoring, diff comparison, annotations, step summaries, PR comments) |
| `tff lint --fail-level error` | Run linter and exit non-zero on error severity violations |
| `tff lint --fail-level warning` | Exit non-zero on any error or warning violations |
| `tff lint --format github` | Output pure GitHub Actions annotations (`::error` / `::warning`) directly to stdout |
| `tff lint --format sarif` | Output OASIS SARIF v2.1.0 JSON format for security/code scanning tools |
| `tff lint --junit-xml PATH` | Output JUnit XML test result format for CI/CD test tabs |
| `tff health --fail-under 80.0` | Exit non-zero if overall health score falls below 80.0% |
| `tff health --scope models/marts` | Restrict health evaluation to a specific path prefix |
