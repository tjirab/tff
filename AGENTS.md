# Agent Task Workflow Rule

Whenever you pick up any new development, feature implementation, or bug-fixing task in this repository, you **must** strictly follow the end-to-end task processing pipeline defined in [.AI/AGENT_TASK_WORKFLOW.md](file:///Users/bartschuijt/git/tff/.AI/AGENT_TASK_WORKFLOW.md).

## Mandatory Steps Summary
1. **Sync Main Branch**: Switch to `main` and pull the latest changes.
2. **Create Feature Branch**: Create a branch prefixed with `feat/`, `fix/`, or `chore/`.
3. **Implementation**: Code the solution adhering to existing patterns.
4. **Add Tests**: Write tests and ensure they cover new changes (with 100% diff coverage per `.githooks/pre-push`).
5. **Documentation Update**: Update `README.md`, API doc, and comments as needed.
6. **Self-Review**: Run the self-review checklist.
7. **Final Commit & PR**: Stage, commit with the appropriate ticket pattern, push, and open a Pull Request. **Ensure the Pull Request title and description are always fully filled in according to the template in `.github/pull_request_template.md` (do not leave them blank or rely on --fill if it produces an empty/incomplete description).**

Do not skip any steps.
