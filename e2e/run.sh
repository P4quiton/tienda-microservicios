#!/usr/bin/env bash
set -uo pipefail
E2E="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ "${1:-}" == "--stubs" ]]; then
  shift
  exec "$E2E/run-stubs.sh" "$@"
fi
exec python3 "$E2E/tests/real_e2e.py" "$@"
