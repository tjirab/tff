#!/usr/bin/env bash
# Ad-hoc script to generate VHS terminal demo GIFs for README.md and documentation.
# Requirements: vhs, ffmpeg, ttyd
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${ROOT_DIR}"

usage() {
    cat <<EOF
Usage: $(basename "$0") [TARGET]

Ad-hoc generation of VHS terminal demo GIFs.

Targets:
  all         Generate all demo GIFs (default)
  dbt         Generate demo.gif (dbt check)
  sqlmesh     Generate demo-sqlmesh.gif (SQLMesh check & CTE fingerprinting)
  health      Generate demo-health.gif (project health scoring)
  <file.tape> Generate demo GIF from a specific tape file

Options:
  -h, --help  Show this help message

Prerequisites:
  brew install vhs ffmpeg ttyd
EOF
}

TARGET="${1:-all}"

if [[ "${TARGET}" == "-h" || "${TARGET}" == "--help" ]]; then
    usage
    exit 0
fi

echo "==> Verifying recording dependencies..."
command -v vhs >/dev/null 2>&1 || { echo "Error: 'vhs' is not installed. Install with 'brew install vhs'." >&2; exit 1; }
command -v ffmpeg >/dev/null 2>&1 || { echo "Error: 'ffmpeg' is not installed. Install with 'brew install ffmpeg'." >&2; exit 1; }
command -v ttyd >/dev/null 2>&1 || { echo "Error: 'ttyd' is not installed. Install with 'brew install ttyd'." >&2; exit 1; }

# Ensure virtual environment exists with tff CLI
if [ ! -f ".venv/bin/tff" ]; then
    echo "==> .venv/bin/tff not found. Running 'uv sync' to set up local environment..."
    uv sync
fi

mkdir -p docs/assets

run_tape() {
    local tape_file="$1"
    local desc="$2"
    echo "==> Generating ${desc} using ${tape_file}..."
    vhs "${tape_file}"
}

case "${TARGET}" in
    all)
        run_tape "demos/demo-check-dbt.tape" "demo.gif (dbt check)"
        run_tape "demos/demo-sqlmesh.tape" "demo-sqlmesh.gif (SQLMesh check & CTE fingerprinting)"
        run_tape "demos/demo-health.tape" "demo-health.gif (project health scoring)"
        ;;
    dbt|check-dbt|demo-check-dbt|demo-check-dbt.tape)
        run_tape "demos/demo-check-dbt.tape" "demo.gif (dbt check)"
        ;;
    sqlmesh|demo-sqlmesh|demo-sqlmesh.tape)
        run_tape "demos/demo-sqlmesh.tape" "demo-sqlmesh.gif (SQLMesh check & CTE fingerprinting)"
        ;;
    health|demo-health|demo-health.tape)
        run_tape "demos/demo-health.tape" "demo-health.gif (project health scoring)"
        ;;
    *)
        if [ -f "${TARGET}" ]; then
            run_tape "${TARGET}" "${TARGET}"
        elif [ -f "demos/${TARGET}" ]; then
            run_tape "demos/${TARGET}" "${TARGET}"
        else
            echo "Error: Unknown target or tape file '${TARGET}'" >&2
            usage
            exit 1
        fi
        ;;
esac

echo "==> Demo generation finished successfully!"
