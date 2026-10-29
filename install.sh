#!/usr/bin/env bash
set -euo pipefail
BEATOS_CODE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
exec python3 -B "$BEATOS_CODE/installer.py"
