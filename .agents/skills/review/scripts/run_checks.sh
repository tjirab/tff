#!/usr/bin/env bash
# Helper script to execute all verification gates for review.
set -euo pipefail

echo "========================================="
echo "Running Review Verification Checks"
echo "========================================="

echo "--> Step 1/4: Ruff Linter"
uv run ruff check .

echo "--> Step 2/4: Dependency Security Audit"
uv run python scripts/audit.py --min-severity HIGH

echo "--> Step 3/4: Pytest Suite with Coverage"
MAX_FORK_WORKERS=1 uv run pytest --cov=packages --cov-report=xml

echo "--> Step 4/4: Enforcing 100% Diff Coverage against origin/main"
uv run diff-cover coverage.xml --compare-branch=origin/main --fail-under=100

echo "========================================="
echo "All validation gates passed successfully!"
echo "========================================="
