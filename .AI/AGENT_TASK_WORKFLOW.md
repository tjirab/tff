# Agent Workflow Guide: Standard Task Processing Pipeline

This document outlines the mandatory end-to-end process for agents when undertaking any new development or feature implementation task. Adherence to this workflow ensures consistency, minimizes merge conflicts, maintains code quality, and provides a clear audit trail.

## 🚀 Workflow Steps

The entire process must be treated as an atomic unit, moving sequentially from step 1 through 6. Do not skip steps, even if they appear redundant at first glance.

### Step 1: Fetch Remote Base (Foundation)
**Goal:** Ensure the local repository has the latest remote state without disturbing any active working trees.
**Action:**
```bash
git fetch origin main
```
**Verification:** Confirm that `origin/main` is up to date and remote changes have been fetched cleanly.

### Step 2: Create Isolated Git Worktree & Feature Branch (Tandem Isolation)
**Goal:** Isolate all work into a dedicated, self-contained git worktree. This enables working on multiple changes in tandem without branch switching, file collisions, or dirtying other workspaces.
**Action:**
1. Determine branch name:
   - `feat/<task-summary>` for new features
   - `fix/<bug-ticket-id>` for bug fixes
   - `chore/<task-summary>` for maintenance/tooling
2. Provision the worktree in a dedicated worktree directory (e.g. `../agent-worktrees`):
   ```bash
   WORKTREE_DIR="../agent-worktrees/tff-<branch-slug>"
   git worktree add -b <branch-name> "$WORKTREE_DIR" origin/main
   ```
3. Set up the development environment inside the worktree:
   ```bash
   cd "$WORKTREE_DIR"
   uv sync
   ```
**Verification:** Confirm with `git worktree list` that the new worktree is registered. Perform all implementation, testing, and git operations (Steps 3 through 6) within `$WORKTREE_DIR`.

### Step 3: Implementation (Coding)
**Goal:** Write, refactor, or modify the core logic to fulfill the requirements defined in the task scope/ticket.
**Action:** Develop all necessary code changes inside the worktree. Adhere strictly to existing codebase patterns and style guides. Commit logical chunks of work as they are completed.

### Step 4: Add Tests (Validation)
**Goal:** Write comprehensive tests that prove the implemented feature/fix works correctly under all specified conditions, including edge cases and failure paths.
**Action:**
1. Write unit tests for all new logic.
2. Update integration or end-to-end tests if the change affects public interfaces.
3. Verify linting and test coverage meets project requirements (enforce 100% diff coverage per `.githooks/pre-push`):
   ```bash
   uv run ruff check .
   MAX_FORK_WORKERS=1 uv run pytest --cov=packages --cov-report=xml
   uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=100
   ```

### Step 5: Documentation Update (Knowledge Transfer)
**Goal:** Ensure all relevant knowledge artifacts are updated to reflect the changes.
**Action:**
1. Update README files, API documentation, and internal comments.
2. If the change involves user-facing features, update necessary guides or tutorials.

### Step 6: Final Commit, PR & Worktree Cleanup (Completion)
**Goal:** Create a clean history, initiate formal review, and manage worktree lifecycle.
**Action:**
1. Stage all final changes (`git add .`).
2. Commit with a comprehensive, atomic message referencing the ticket/issue:
   ```bash
   git commit -m "feat(scope): Descriptive summary of the change and why it was needed."
   ```
3. Push the branch to origin:
   ```bash
   git push -u origin <branch-name>
   ```
4. Create a Pull Request (PR) against `main` with `gh pr create`:
   **Ensure the PR title and description are fully populated using the template at `.github/pull_request_template.md` (do not leave it blank or rely solely on `--fill` if it results in an empty description).**
5. Worktree Cleanup:
   Once the PR is created and verified, either retain the worktree for review feedback or safely remove it:
   ```bash
   git worktree remove "$WORKTREE_DIR"
   ```


## 🚨 Mandatory Principles
*   **Atomic Commits:** Each commit should represent one logical change. Do not group unrelated fixes or features into a single commit message.
*   **Test-Driven Approach:** Write tests *before* or concurrently with implementation whenever possible to ensure correctness from the start.
*   **Review First Mindset:** Treat every step as if you are being reviewed, forcing early checks for completeness and clarity.

