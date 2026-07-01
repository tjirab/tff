# Agent Workflow Guide: Standard Task Processing Pipeline

This document outlines the mandatory end-to-end process for agents when undertaking any new development or feature implementation task. Adherence to this workflow ensures consistency, minimizes merge conflicts, maintains code quality, and provides a clear audit trail.

## 🚀 Workflow Steps

The entire process must be treated as an atomic unit, moving sequentially from step 1 through 7. Do not skip steps, even if they appear redundant at first glance.

### Step 1: Sync Main Branch (Foundation)
**Goal:** Ensure the local development environment is based on the absolute latest state of the main codebase.
**Action:**
```bash
git checkout main
git pull origin main
```
**Verification:** Confirm that the current active branch is `main` and that all remote changes have been successfully integrated.

### Step 2: Create Feature Branch (Isolation)
**Goal:** Isolate all work into a dedicated, traceable branch.
**Action:**
```bash
# Use descriptive prefixes based on ticket type or scope.
git checkout -b feat/<task-summary> # For new features
# git checkout -b fix/<bug-ticket-id> # For bug fixes
# git checkout -b chore/<maintenance-task> # For non-functional changes (e.g., dependencies)
```
**Verification:** The current active branch must match the specified naming convention and contain only work related to the task description.

### Step 3: Implementation (Coding)
**Goal:** Write, refactor, or modify the core logic to fulfill the requirements defined in the task scope/ticket.
**Action:** Develop all necessary code changes. Use high-quality coding standards, adhering strictly to existing codebase patterns and style guides. Commit logical chunks of work as they are completed (but not necessarily committed yet).

### Step 4: Add Tests (Validation)
**Goal:** Write comprehensive tests that prove the implemented feature/fix works correctly under all specified conditions, including edge cases and failure paths.
**Action:**
1.  Write unit tests for all new logic.
2.  Update integration or end-to-end tests if the change affects public interfaces.
3.  Ensure test coverage metrics meet the project's defined minimum threshold (e.g., > 80%).

### Step 5: Documentation Update (Knowledge Transfer)
**Goal:** Ensure all relevant knowledge artifacts are updated to reflect the changes.
**Action:**
1.  Update README files, API documentation, and internal comments.
2.  If the change involves user-facing features, update necessary guides or tutorials.

### Step 6: Self-Review (Quality Gate)
**Goal:** Proactively review the entire contribution as if preparing for a peer review.
**Checklist:**
*   [ ] Does the code only implement what was asked? (No scope creep).
*   [ ] Are variable/function names clear and self-explanatory?
*   [ ] Is there adequate error handling (`try...except` blocks, graceful failure)?
*   [ ] Does the documentation accurately reflect behavior?
*   [ ] Are all necessary dependencies or environmental setup changes noted?

### Step 7: Final Commit & PR (Completion)
**Goal:** Create a clean history and initiate formal review.
**Action:**
1.  Stage all final changes (`git add .`).
2.  Commit with a comprehensive, atomic message that references the original task/ticket ID.
    ```bash
    git commit -m "feat(scope): [TICKET-ID] Descriptive summary of the change and why it was needed."
    ```
3.  Push the branch (`git push origin <branch-name>`).
4.  Create a Pull Request (PR) against `main` with `gh pr create`, ensuring all changes are logically grouped and ready for peer review.

## 🚨 Mandatory Principles
*   **Atomic Commits:** Each commit should represent one logical change. Do not group unrelated fixes or features into a single commit message.
*   **Test-Driven Approach:** Write tests *before* or concurrently with implementation whenever possible to ensure correctness from the start.
*   **Review First Mindset:** Treat every step as if you are being reviewed, forcing early checks for completeness and clarity.

