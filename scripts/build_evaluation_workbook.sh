#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE="/Users/huihuafei/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
NODE_MODULES="/Users/huihuafei/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"

ln -sfn "$NODE_MODULES" "$ROOT/node_modules"
trap 'rm -f "$ROOT/node_modules"' EXIT
"$ROOT/scripts/generate_search_matrix.py"
"$NODE" "$ROOT/scripts/build_evaluation_workbook.mjs"
