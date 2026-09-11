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

### Engine Compilation & Baseline Comparison (dbt, SQLMesh, Dataform)

When running in CI/CD, different transformation engines handle metadata, DAG compilation, and base branch comparisons differently.

#### Engine Comparison Matrix

| Engine | Compilation Required? | How Feature Branch is Evaluated | How Base Branch (`main`) is Evaluated | Does `only-changed: true` require compiling `main`? |
| :--- | :--- | :--- | :--- | :--- |
| **SQLMesh** | ❌ **No** | Python AST & SQLGlot semantic parser (`Context`) | Independent in-memory `Context` on temp worktree | ❌ **No** (`git diff` only) |
| **Dataform** | ⚠️ **Optional** | Precompiled manifest, CLI on-the-fly, or static `.sqlx` fallback | Static `.sqlx` AST parser or on-the-fly CLI compile | ❌ **No** (`git diff` only) |
| **dbt** | ✅ **Yes** (`dbt compile`) | Reads local `target/manifest.json` | Requires `manifest.json` (or gracefully skips baseline delta) | ❌ **No** (`git diff` only) |

#### 1. Crucial Distinction: Gating vs. Score Diffing

It is important to separate **changed-files gating** from **baseline score diffing**:

* **`only-changed: true` Gating**:
  Uses Git commit history (`git diff origin/${base_ref}...HEAD --name-only`) to find which models/files were touched in the PR, and filters the violations in the current project.
  **This does NOT require compiling `main` or having a manifest for `main`**. It works immediately out of the box for dbt, SQLMesh, and Dataform alike.
* **Baseline Score Diffing (`diff-against-base: true`)**:
  Computes the health score delta (`+2.5% vs main 📈` or `-1.0% vs main 📉`) by checking out `origin/${base_ref}` in a detached temporary git worktree.

#### 2. SQLMesh: Zero-Compilation Native Evaluation
SQLMesh parses `.sql` and `.py` model definitions directly into an AST using SQLGlot and Python's semantic engine.
* **In-Memory Analysis**: TFF instantiates an in-memory SQLMesh `Context` via `FitnessLoader` on both the feature branch and the temporary git worktree for `main`.
* **Zero Credentials**: No warehouse connection or database profile is required.
* **Instant Diffing**: Baseline comparison against `main` runs automatically and instantly in memory.

#### 3. Dataform: 3-Tier Resolution Strategy
TFF resolves Dataform projects via a 3-tier fallback strategy:
1. **Tier 1 (Cached Manifest)**: If `compilation_result.json` exists, TFF parses it.
2. **Tier 2 (On-the-Fly CLI Compilation)**: If `dataform` CLI or `npx @dataform/cli` is present on `PATH`, TFF compiles `main` in memory.
3. **Tier 3 (Zero-Tooling Static Parser)**: If neither a manifest nor Node/Dataform CLI exists, TFF uses its built-in `.sqlx` parser (`_load_from_sqlx_files`) to extract `config { ... }` blocks and dependencies directly from source files.

Both branches evaluate seamlessly without requiring a compiled artifact committed to Git.

#### 4. dbt: The `manifest.json` Challenge & CI Best Practices
dbt relies on Jinja macros, package dispatch (`dbt_utils`), and adapter configs that require `dbt compile` or `dbt parse` to generate `target/manifest.json`.

* **Feature Branch**: You must compile the current PR branch before running TFF:
  ```yaml
  - name: Compile dbt
    run: dbt compile

  - name: Run TFF Action
    uses: tjirab/tff@v1
    with:
      provider: "dbt"
      only-changed: "true"
  ```
* **Base Branch (`main`)**: Because `target/` is gitignored by default, checking out `origin/main` in a temporary worktree creates a clean directory with no `target/manifest.json`.
  * **Default Behavior**: TFF catches the missing manifest in `main` gracefully, logs a notice, and skips the baseline score delta. **The workflow does not fail**—the PR is still fully gated on health thresholds and violations in touched files.
* **Enabling Baseline Score Diffing for dbt**:
  * **Pattern A: Slim CI Artifact Cache (Recommended)**: Download the latest production `manifest.json` from your CI cache or cloud storage (e.g. S3, GCS) into your baseline directory, matching dbt Slim CI practices (`dbt --defer --state`).
  * **Pattern B: Pre-compile `main` in Runner**: If warehouse credentials are available in the CI runner:
    ```yaml
    - name: Compile Base Branch
      run: |
        git checkout ${{ github.base_ref }}
        dbt compile --target-path target-base
        git checkout -
        dbt compile
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
