#!/usr/bin/env bash
# Ad-hoc script to generate VHS terminal demo GIFs.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

exec "${ROOT_DIR}/demos/generate_demos.sh" "$@"
