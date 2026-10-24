#!/usr/bin/env bash
# Start NekoStudio. Extra args go to the server (e.g. --port 7861, --open).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
[ -x .venv/bin/python ] || { echo "No .venv yet. Run ./setup.sh first." >&2; exit 1; }
exec .venv/bin/python -m nekostudio --open "$@"
