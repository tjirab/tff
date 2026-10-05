# Agent Task Workflow Rule

Whenever you pick up any new development, feature implementation, or bug-fixing task in this repository, you **must** strictly follow the end-to-end task processing pipeline defined in [.AI/AGENT_TASK_WORKFLOW.md](.AI/AGENT_TASK_WORKFLOW.md).

## Mandatory Steps Summary
1. **Sync Base**: Fetch latest remote updates (`git fetch origin main`).
2. **Create Git Worktree**: Provision an isolated worktree under `../agent-worktrees/tff-<branch>` to enable working on multiple changes in tandem.
3. **Implementation**: Code the solution adhering to existing patterns within the worktree.
4. **Add Tests**: Write tests and ensure they cover new changes (with 100% diff coverage per `.githooks/pre-push`).
   - **Pure Core, Thin Shell**: Test business logic directly as pure data transformations. Presentation formatters (Rich, ANSI, Markdown) must have separate, minimal smoke tests. Never assert business logic through terminal formatting strings.
   - **Parametrization**: Require `@pytest.mark.parametrize` for permutation and matrix testing; do not write duplicate test functions.
   - **Test Factories**: Mandate test factory helpers (`_make_finding`, `_make_model` in `conftest.py`) instead of verbose, repeated dataclass or dictionary instantiations.
5. **Documentation Update**: Update `README.md`, API doc, and comments as needed.
6. **Final Commit, PR & Cleanup**: Stage, commit with the appropriate ticket pattern, push, open a Pull Request adhering to `.github/pull_request_template.md`, and clean up or retain the worktree.

Do not skip any steps.
