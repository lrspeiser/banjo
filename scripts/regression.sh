#!/usr/bin/env bash
# Cross-platform runner owns only its own build/test children. --list never
# builds, cleans or stops processes. The Python runner validates discovery.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1
if command -v python3 >/dev/null 2>&1; then
    exec python3 scripts/regression.py "$@"
else
    exec python scripts/regression.py "$@"
fi
