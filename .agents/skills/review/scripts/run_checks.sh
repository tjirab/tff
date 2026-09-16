#!/usr/bin/env bash
# Helper script to execute all verification gates for review.
# Note: Linting is skipped as it is already enforced in CI.
set -euo pipefail

echo "========================================="
echo "Running Review Verification Checks"
echo "========================================="

echo "--> Step 1/3: Dependency Security Audit"
uv run python scripts/audit.py --min-severity HIGH

echo "--> Step 2/3: Pytest Suite with Coverage"
MAX_FORK_WORKERS=1 uv run pytest --cov=packages --cov-report=xml

echo "--> Step 3/3: Enforcing 100% Diff Coverage against origin/main"
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=100

echo "========================================="
echo "All validation gates passed successfully!"
echo "========================================="
