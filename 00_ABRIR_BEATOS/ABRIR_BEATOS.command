#!/bin/bash
set -euo pipefail
BEATOS_ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
exec python3 "$BEATOS_ROOT/serve_mpc.py" "$BEATOS_ROOT"
