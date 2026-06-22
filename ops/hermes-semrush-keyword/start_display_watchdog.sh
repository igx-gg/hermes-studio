#!/usr/bin/env bash
set -euo pipefail

BASE_DIR="${HERMES_DISPLAY_DIR:-/home/agent/.hermes/display}"
SCRIPT_DIR="${SEMRUSH_SCRIPT_DIR:-/home/agent/.hermes/scripts/semrush-keyword}"
WATCHDOG="$SCRIPT_DIR/display_watchdog.py"
ENV_FILE="${HERMES_ENV_FILE:-/home/agent/.hermes/.env}"

mkdir -p "$BASE_DIR/logs" /tmp/hermes-runtime-root

if [ -f "$ENV_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

if [ ! -f "$WATCHDOG" ]; then
  echo "display watchdog not found: $WATCHDOG" >&2
  exit 1
fi

if pgrep -f "$WATCHDOG" >/dev/null 2>&1; then
  echo "display watchdog already running"
  exit 0
fi

setsid -f bash -lc "exec /opt/hermes/.venv/bin/python '$WATCHDOG' >>'$BASE_DIR/logs/watchdog.log' 2>&1 </dev/null"
echo "display watchdog started"
