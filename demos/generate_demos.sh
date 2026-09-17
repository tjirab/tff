#!/usr/bin/env bash
# Generate all VHS demo GIFs for README.md and documentation.
# Requirements: vhs, ffmpeg, ttyd
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

echo "==> Verifying dependencies..."
command -v vhs >/dev/null 2>&1 || { echo "Error: 'vhs' is not installed. Install with 'brew install vhs'." >&2; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "Error: 'ffmpeg' is not installed. Install with 'brew install ffmpeg'." >&2; exit 1; }
command -v ttyd >/dev/null 2>&1 || { echo "Error: 'ttyd' is not installed. Install with 'brew install ttyd'." >&2; exit 1; }

mkdir -p docs/assets

echo "==> Generating demo.gif (dbt check)..."
vhs demos/demo-check-dbt.tape

echo "==> Generating demo-sqlmesh.gif (SQLMesh check & CTE fingerprinting)..."
vhs demos/demo-sqlmesh.tape

echo "==> Generating demo-health.gif (project health scoring)..."
vhs demos/demo-health.tape

echo "==> All demo GIFs successfully created in docs/assets/!"
