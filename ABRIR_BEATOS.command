#!/bin/bash
set -euo pipefail
BEATOS_CODE="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 -B "$BEATOS_CODE/serve_mpc.py"
