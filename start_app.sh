#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${1:-8080}"

# Check for Python binary
PYTHON_BIN=""
if [[ -x "$SCRIPT_DIR/bin/python3" ]]; then
    PYTHON_BIN="$SCRIPT_DIR/bin/python3"
elif command -v python3 &>/dev/null; then
    PYTHON_BIN="python3"
elif [[ -x "/Library/Frameworks/Python.framework/Versions/3.15/bin/python3" ]]; then
    PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.15/bin/python3"
fi

if [[ -z "$PYTHON_BIN" ]]; then
    echo "Error: Python 3 not found."
    exit 1
fi

echo "=========================================================="
echo " Starting Database Log Checker Web App..."
echo " Using: $PYTHON_BIN"
echo " Port:  $PORT"
echo " URL:   http://localhost:$PORT"
echo "=========================================================="

exec "$PYTHON_BIN" "$SCRIPT_DIR/server.py" "$PORT"
