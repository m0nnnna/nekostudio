#!/usr/bin/env bash
# Start NekoStudio. Extra args go to the server (e.g. --port 7861, --open).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
. ./nekoenv.sh
[ -x "$ENV_DIR/.venv/bin/python" ] || { echo "No Python env yet. Run ./setup.sh first." >&2; exit 1; }
exec "$ENV_DIR/.venv/bin/python" -m nekostudio --open "$@"
