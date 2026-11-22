#!/usr/bin/env bash
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.beatos/bin:$PATH"
BEATOS_CODE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BEATOS_VENV="${BEATOS_VENV_DIR:-$HOME/.beatos/venv}"
BEATOS_PY=""
for cand in "$BEATOS_VENV/bin/python" "$BEATOS_CODE/.venv/bin/python" "$HOME/.mlx-stack/venv/bin/python"; do
  if [ -x "$cand" ]; then
    BEATOS_PY="$cand"
    break
  fi
done
if [ -n "$BEATOS_PY" ]; then
  exec "$BEATOS_PY" -B "$BEATOS_CODE/installer.py" "$@"
fi
exec python3 -B "$BEATOS_CODE/installer.py" "$@"
