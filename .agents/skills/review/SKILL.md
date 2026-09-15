---
name: review
description: >-
  Conduct a rigorous, objective code review of a pull request, branch, or staged changes.
  Reviews strictly for security, performance, feature coverage, and test coverage.
  Omits praise and conversational fluff. Automatically triages non-blocking improvements into GitHub issues using `gh issue create`.
  Trigger with `/review` or `/review <pr_or_branch>`.
---

# Code Review Process (`/review`)

This skill defines the mandatory, objective code review procedure for pull requests, branches, and working changes.

---

## 🎯 Review Core Principles

1. **Zero Flattery / Avoid Praise**:
   - Do NOT include empty compliments or conversational filler (e.g., "Great work!", "Looks clean!", "Nice approach!", "Thanks for this PR!").
   - Reviews must be purely technical, concise, factual, and direct. Focus entirely on verification, findings, risk assessment, and actionable feedback.

2. **Rigorous Four-Pillar Inspection**:
   - **Security**: Credential leakage in logs/CLI, injection risks, unsafe deserialization, filesystem traversal, token permission scoping.
   - **Performance**: Algorithmic complexity, AST caching efficiency, parallel processing bottlenecks, redundant allocations, memory scaling.
   - **Feature Coverage**: Full fulfillment of ticket/PR requirements, CLI options, backward compatibility, edge case & error handling.
   - **Test Coverage**: Unit & integration test adequacy, negative/failure path testing.

3. **Automated Triage of Non-Blocking Improvements**:
   - Distinguish strictly between **Blocking Issues** (must be resolved before merge) and **Non-Blocking Improvements** (technical debt, minor refactoring, future enhancements, secondary docs).
   - **ALL non-blocking improvements must be automatically created as GitHub issues** using `gh issue create` during the review turn. Include links to the newly opened issues in the review response.

---

## 🛠️ Step-by-Step Review Procedure

### Step 1: Identify Review Target & Inspect Changes
1. Determine the target from the command:
   - If argument is given (e.g., `/review 191`, `/review tff#191`, `/review feat/branch-name`):
     ```bash
     # For PR:
     gh pr view <pr_number> --json number,title,body,headRefName,baseRefName,files
     gh pr diff <pr_number>
     ```
   - If no argument is given:
     - Check if current branch has an associated open PR (`gh pr view --json number,title,body,headRefName,baseRefName,files`).
     - Otherwise, inspect local diff against `main` (`git diff origin/main...HEAD`).

2. View the complete diff and all modified/added files in detail.

### Step 2: Automated Verification Run
Run the repository validation suite locally (or inspect CI checks if review target is a remote PR):
```bash
# 1. Linting
uv run ruff check .

# 2. Dependency security audit
uv run python scripts/audit.py --min-severity HIGH

# 3. Unit tests
MAX_FORK_WORKERS=1 uv run pytest
```
Note any failures, warnings, or missing tests.

### Step 3: Deep Technical Inspection

#### A. Security Review
- **Credentials & Secrets**: Are API tokens, keys, passwords, or auth headers printed to stdout/stderr or written into logs, cache files, or error messages? (e.g., `--github-token`, webhook URLs).
- **Injection & Sanitization**: Are SQL strings, regex expressions, or shell commands dynamically concatenated from unvalidated inputs?
- **Deserialization**: Is `pickle` or `yaml.load` used safely? When loading cached ASTs or manifests, are errors caught and corrupt files purged safely?
- **File System Safety**: Are file writes atomic (`tempfile` + `replace`)? Are paths bounded to project root to prevent path traversal?

#### B. Performance Review
- **Algorithmic Complexity**: Are lookups O(1) using sets/dicts where appropriate instead of repeated list scans?
- **AST Caching**: Does new AST parsing leverage `parse_sql_with_cache` or `get_cached_ast`? Are cache keys properly formed?
- **Worker Concurrency**: In parallel tasks, are `ThreadPoolExecutor` (I/O bound) and `ProcessPoolExecutor` (CPU/AST parsing bound) used appropriately? Is thread safety maintained?
- **Resource Cleanup**: Are file handles, temporary files, and executors closed properly (`with` statements)?

#### C. Feature & Functional Coverage
- **Specification Fulfillment**: Does the change completely satisfy the PR/issue description without unintended scope creep?
- **CLI & Interface Consistency**: Are CLI flags added to parent parsers and subparsers consistently? Are help strings, types, and defaults accurate?
- **Error Handling**: Are custom exceptions caught gracefully, printing meaningful error messages to `stderr` and returning appropriate non-zero exit codes?
- **Documentation**: Are `README.md`, `docs/cli.md`, or relevant user guides updated?

#### D. Test Coverage
- **Edge Cases & Failure Paths**: Are error conditions, invalid arguments, missing config files, and environment variable overrides explicitly tested?

---

### Step 4: Triage Non-Blocking Improvements to GitHub Issues
For every valid suggestion, optimization, or follow-up task that is **not** a blocker for merging the current PR:
1. Formulate a clear title using conventional commits: `chore(<scope>): ...`, `docs(<scope>): ...`, `perf(<scope>): ...`, or `security(<scope>): ...`.
2. Construct a detailed markdown body explaining the context, problem, and proposed solution.
3. Determine appropriate labels (e.g., `core`, `rules`, `enhancement`, `documentation`, `autofix`).
4. Execute `gh issue create`:
   ```bash
   gh issue create --title "<title>" --label "<labels>" --body "<body_content>"
   ```
5. Record the generated issue URL to report back in the review.

---

### Step 5: Format the Review Report

Deliver the review using the following standardized template:

```markdown
# Code Review: PR #<number> / <target> — `<title>`

## 📊 Summary
- **Target**: PR #<number> (`<head-branch>` -> `<base-branch>`)
- **Diff Stat**: <X> files changed, <+Y> additions, <-Z> deletions
- **Automated Validation**:
  - Ruff: `Pass` / `Fail`
  - Audit: `Pass` / `Fail`
  - Unit Tests: `<N>/<N> passed`

---

## 🛡️ Security Analysis
<Bullet points evaluating security considerations or confirming safe implementation>

---

## ⚡ Performance Analysis
<Bullet points evaluating algorithmic complexity, caching, concurrency, and resource management>

---

## 🧩 Feature & Functional Coverage
<Bullet points evaluating requirement completeness, error handling, interface consistency, and edge cases>

---

## 🧪 Test Coverage
<Bullet points evaluating test assertions, edge cases tested, and diff coverage verification>

---

## ⛔ Blocking Issues
<List of must-fix issues before merge. If none, state: "None. All blocking criteria satisfied.">

---

## 📋 Triaged GitHub Issues (Non-Blocking)
<List of created GitHub issues for non-blocking improvements. If none, state: "None.">
- [#<issue-number>: `<issue-title>`](<issue-url>)
  - **Summary**: <1-sentence description>

---

## 🏁 Verdict
**<APPROVE | REQUEST_CHANGES | COMMENT>**
<1-2 sentence final summary stating reason for verdict>
```
