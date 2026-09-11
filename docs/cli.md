# CLI Reference & Usage Guide

Transformation Fitness Functions (**TFF**) provides a unified, zero-config command-line interface (`tff`) to run architectural fitness functions, compute project health scores, generate documentation dashboards, and integrate with CI/CD quality gates.

---

## 1. Command Overview

The CLI provides the following subcommands:

| Subcommand | Description | Primary Use Case |
| :--- | :--- | :--- |
| [`tff lint`](#3-tff-lint) | Evaluates fitness checks and reports violations | Local pre-commit checks, CI lint steps, autofixing |
| [`tff health`](#4-tff-health) | Calculates overall health score (0–100) and penalties | Quality thresholds, domain health breakdowns |
| [`tff action`](#5-tff-action) | Runs the official GitHub Action pipeline locally or in CI | Base branch diff scoring, PR comments, annotations |
| [`tff docs`](#6-tff-docs) | Generates interactive HTML report with lineage graphs | Architectural dashboards, team documentation |
| [`tff init`](#7-tff-init) | Scaffolds an annotated starter `fitness_functions.yaml` | Onboarding new projects to custom fitness rules |
| [`tff stats`](#8-tff-stats) | Displays historical execution trends and metric logs | Tracking architectural drift over time |
| [`tff info`](#9-tff-info) | Prints diagnostic info about environment and adapters | Debugging engine discovery, site-packages, config |
| [`tff help`](#10-tff-help) | Displays help and usage information for commands | Exploring command arguments and syntax |

---

## 2. Global Conventions & Defaults

* **Zero-Config Fallback**: If no `fitness_functions.yaml` is present, TFF automatically infers standard architectural layer conventions (`staging` &rarr; `intermediate` &rarr; `core` &rarr; `marts`) and runs all baseline rules.
* **Auto-Discovery**: TFF automatically detects the project engine (`dbt`, `SQLMesh`, or `Dataform`) by scanning configuration files in the target directory.
* **Local Run Logging**: Executions of `tff lint` and `tff health` automatically save run metrics to `.tff_logs/` in JSON format (retained for 60 days). Disable anytime with `--no-log` or `export TFF_NO_LOG=1`.
* **Exit Codes**:
  * `0`: Success (all checks passed, health score at or above threshold).
  * `1`: Quality failure (violations found at or above fail-level, or health score below threshold).
  * `2`: CLI usage or argument parsing error.

---

## 3. `tff lint`

Run architectural and SQL quality fitness checks against project models.

```bash
tff lint [options]
```

### Options Reference Table

| Option | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- |
| `--project PATH` | Directory Path | `.` (current dir) | Project root directory. |
| `--config PATH` | File Path | `fitness_functions.yaml` | Path to fitness functions config (relative to project root). |
| `--provider` | `auto`, `dbt`, `sqlmesh`, `dataform` | `auto` | Pipeline engine provider (auto-detected if omitted). |
| `--checks CHECKS` | Comma-separated string | (all enabled) | Specific checks to run (e.g. `layer_integrity,ban_select_star`). |
| `--fail-level` | `error`, `warning` | `error` | Exit with code `1` if findings at or above this severity exist. |
| `--group-by` | `model`, `connascence` | `model` | How to group violations in the console report. |
| `--dialect DIALECT` | String | (auto-inferred) | SQL dialect of models (e.g. `duckdb`, `snowflake`, `bigquery`). |
| `--manifest PATH` | File Path | (auto-discovered) | Path to precompiled manifest (dbt `manifest.json` or Dataform `compilation_result.json`). |
| `--fix` | Flag | `false` | Automatically fix simple violations (e.g. rewrite positional `GROUP BY`/`ORDER BY` and scaffold missing metadata). |
| `--format` | `text`, `json`, `sarif`, `github` | `text` | Output format to stdout. |
| `--json` | Flag | `false` | Shorthand for `--format json`. |
| `--github-annotations` | Flag | (auto if CI) | Emit GitHub Actions workflow commands (`::error` / `::warning`) to stderr. |
| `--junit-xml PATH` | File Path | (none) | Write JUnit XML test report for CI results tabs (GitLab, Azure DevOps, Bitbucket). |
| `--no-log` | Flag | `false` | Disable writing execution logs to `.tff_logs/lint/`. |

### Examples

```bash
# Standard linting run (zero-config out of the box)
tff lint

# Run specific rules only
tff lint --checks layer_integrity,ban_select_star

# Auto-fix fixable violations
tff lint --fix

# Export SARIF for GitHub Code Scanning
tff lint --format sarif > results.sarif

# Export JUnit XML for GitLab CI or Azure DevOps
tff lint --junit-xml reports/junit.xml
```

---

## 4. `tff health`

Compute project health scores (0.0 to 100.0) based on weighted connascence categories and violation penalties.

```bash
tff health [options]
```

### Options Reference Table

| Option | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- |
| `--project PATH` | Directory Path | `.` (current dir) | Project root directory. |
| `--config PATH` | File Path | `fitness_functions.yaml` | Path to fitness functions config (relative to project root). |
| `--provider` | `auto`, `dbt`, `sqlmesh`, `dataform` | `auto` | Pipeline engine provider. |
| `--fail-under SCORE` | Float (`0.0` - `100.0`) | `0.0` | Exit with code `1` if overall health score is below this threshold. |
| `--scope PREFIX [...]`| String (one or more) | (entire project) | Restrict evaluation to models starting with given path prefixes. |
| `--group-by` | `connascence`, `domain` | `connascence` | Group breakdown by connascence category or domain folder. |
| `--dialect DIALECT` | String | (auto-inferred) | SQL dialect of models. |
| `--manifest PATH` | File Path | (auto-discovered) | Path to precompiled manifest. |
| `--json` | Flag | `false` | Output results in JSON format to stdout. |
| `--no-log` | Flag | `false` | Disable writing execution logs to `.tff_logs/health/`. |

### Examples

```bash
# Display overall health score and category breakdown
tff health

# Require an 80% health score to pass CI
tff health --fail-under 80

# Restrict health scoring to marketing domain models
tff health --scope models/marts/marketing

# Group breakdown by domain instead of connascence
tff health --group-by domain
```

---

## 5. `tff action`

Run the complete GitHub Action pipeline locally or inside automated container workflows.

```bash
tff action [options]
```

### Options Reference Table

| Option | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- |
| `--project PATH` | Directory Path | `.` | Project root directory. |
| `--provider` | `auto`, `dbt`, `sqlmesh`, `dataform` | `auto` | Pipeline engine provider. |
| `--fail-under SCORE` | Float (`0.0` - `100.0`) | `0.0` | Minimum overall health score required to pass. |
| `--fail-level` | `error`, `warning` | `error` | Failure severity level triggering exit code `1`. |
| `--only-changed` | Flag | `false` | Only gate and report violations for models/files modified in this PR. |
| `--comment-pr {true,false}` | String | `false` | Create or update idempotent PR summary comment on GitHub. |
| `--github-token TOKEN` | String | `$GITHUB_TOKEN` | GitHub API token for PR comments. |
| `--base-ref REF` | String | (auto-detected) | Base branch reference to compare health score against (e.g. `main`). |
| `--diff-against-base` / `--no-diff-against-base` | Flag | `true` | Compute health score diff vs target branch in temporary worktree. |
| `--annotations` / `--no-annotations` | Flag | `true` | Emit GitHub Actions workflow command annotations. |
| `--pr-number NUM` | Integer | (auto-detected) | Pull request number (auto-inferred from `$GITHUB_EVENT_PATH`). |
| `--repo OWNER/REPO` | String | (auto-detected) | GitHub repository full name (auto-inferred from `$GITHUB_REPOSITORY`). |
| `--json` | Flag | `false` | Output final results as JSON to stdout. |

### Examples

```bash
# Test action execution locally against main branch
tff action --base-ref main --fail-under 80

# Only gate modified files in the current branch
tff action --base-ref main --only-changed --fail-under 85
```

---

## 6. `tff docs`

Generate an interactive, standalone HTML health dashboard and documentation report.

```bash
tff docs [options]
```

### Options Reference Table

| Option | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- |
| `--project PATH` | Directory Path | `.` | Project root directory. |
| `--output PATH`, `-o` | File Path | `tff_report.html` | Destination path for generated HTML file. |
| `--config PATH` | File Path | `fitness_functions.yaml` | Path to fitness functions config. |
| `--provider` | `auto`, `dbt`, `sqlmesh`, `dataform` | `auto` | Pipeline engine provider. |
| `--dialect DIALECT` | String | (auto-inferred) | SQL dialect of models. |
| `--manifest PATH` | File Path | (auto-discovered) | Path to precompiled manifest. |
| `--no-log` | Flag | `false` | Disable writing execution logs. |

### Examples

```bash
# Generate dashboard at ./tff_report.html
tff docs

# Custom output destination (e.g. for GitHub Pages / static hosting)
tff docs --output public/index.html
```

---

## 7. `tff init`

Scaffold a fully commented `fitness_functions.yaml` configuration file in the project directory.

```bash
tff init [options]
```

### Options Reference Table

| Option | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- |
| `--project PATH` | Directory Path | `.` | Project root directory. |
| `--force`, `-f` | Flag | `false` | Overwrite existing `fitness_functions.yaml` if one already exists. |

### Examples

```bash
# Scaffold initial configuration
tff init

# Overwrite existing configuration
tff init --force
```

---

## 8. `tff stats`

Inspect execution history, health score trends, and violation frequency from local `.tff_logs/`.

```bash
tff stats [options]
```

### Options Reference Table

| Option | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- |
| `--project PATH` | Directory Path | `.` | Project root directory. |
| `--days DAYS` | Integer | `7` | Number of days of historical execution logs to analyze. |
| `--json` | Flag | `false` | Output stats summary as JSON to stdout. |

### Examples

```bash
# View summary of last 7 days of runs
tff stats

# View last 30 days
tff stats --days 30

# Machine-readable output for telemetry
tff stats --days 30 --json
```

---

## 9. `tff info`

Print diagnostic information about the project environment, active configuration, adapter versions, and discovered model files.

```bash
tff info [options]
```

### Options Reference Table

| Option | Type / Choices | Default | Description |
| :--- | :--- | :--- | :--- |
| `--project PATH` | Directory Path | `.` | Project root directory. |
| `--config PATH` | File Path | `fitness_functions.yaml` | Path to fitness functions config. |
| `--provider` | `auto`, `dbt`, `sqlmesh`, `dataform` | `auto` | Pipeline engine provider. |

### Examples

```bash
tff info
```

---

## 10. `tff help`

Display detailed help for any subcommand:

```bash
tff help [subcommand]
# or
tff [subcommand] --help
```

---

## 11. Output Formats & Integrations

TFF supports multiple structured output formats for seamless CI/CD and tool integration:

| Format | CLI Option | Primary Target | Description |
| :--- | :--- | :--- | :--- |
| **Terminal Text** | (default) | Local developers, CI terminal | Rich colored ASCII tables, violation callouts, and recommendations. |
| **JSON** | `--format json` or `--json` | `jq`, custom telemetry, scripts | Pure JSON output of findings, health scores, and metrics. |
| **SARIF v2.1.0** | `--format sarif` | GitHub Code Scanning | OASIS standard format for GitHub Security Alerts and PR file annotations. |
| **GitHub Annotations**| `--format github` or `--github-annotations` | GitHub Actions Runners | Emits `::error` and `::warning` workflow commands to annotate changed lines in PRs. |
| **JUnit XML** | `--junit-xml PATH` | GitLab CI, Azure DevOps, Bitbucket | Standard XML test report rendered natively in CI pipeline test tabs. |
