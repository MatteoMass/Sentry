#!/usr/bin/env bash
#
# Build the frontend, then serve everything from the backend.
#
# The API mounts `src/frontend/dist/` at `/`, so once the app is built a
# single uvicorn process answers both the API and the page. This script does
# the two steps in that order and leaves the server in the foreground.
#
# Usage:
#   ./run.sh                 build the frontend, then serve on :8016
#   ./run.sh --no-build      serve whatever is already in dist/
#   ./run.sh --reload        reload the backend when the sources change
#   ./run.sh --port 9000     serve somewhere else
#
# The address comes from `server.host` and `server.port` in sentry.yml — or
# from SENTRY_HOST and SENTRY_PORT, which win over the file — and the flags
# above win over both.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FRONTEND_DIR="$PROJECT_ROOT/src/frontend"

FALLBACK_HOST="127.0.0.1"
FALLBACK_PORT="8016"
HOST=""
PORT=""
BUILD=1
RELOAD=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-build|--skip-build) BUILD=0; shift ;;
    --reload) RELOAD=(--reload); shift ;;
    --port) PORT="${2:?--port needs a number}"; shift 2 ;;
    --host) HOST="${2:?--host needs an address}"; shift 2 ;;
    -h|--help) awk 'NR>1 && !/^#/ {exit} NR>1 {sub(/^# ?/, ""); print}' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "run.sh: unknown option '$1' (try --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "run.sh: '$1' is not installed or not on PATH" >&2
    exit 1
  }
}

# ----------------------------------------------------------------- frontend

if [[ $BUILD -eq 1 ]]; then
  need npm

  # `npm ci` is the reproducible install, but it only works with a lock file
  # and it throws away node_modules every time; it is worth it once, and
  # after that only when the lock file has moved on.
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]] \
     || [[ "$FRONTEND_DIR/package-lock.json" -nt "$FRONTEND_DIR/node_modules" ]]; then
    say "Installing frontend dependencies"
    if [[ -f "$FRONTEND_DIR/package-lock.json" ]]; then
      npm ci --prefix "$FRONTEND_DIR"
    else
      npm install --prefix "$FRONTEND_DIR"
    fi
  fi

  say "Building the frontend"
  npm run build --prefix "$FRONTEND_DIR"
fi

if [[ ! -f "$FRONTEND_DIR/dist/index.html" ]]; then
  echo "run.sh: no build in src/frontend/dist — the service will answer the API only" >&2
fi

# ------------------------------------------------------------------ backend

need poetry

# A checkout that has never been installed has no interpreter to run under.
if ! poetry env info --path >/dev/null 2>&1; then
  say "Installing Python dependencies"
  poetry install
fi

if [[ ! -f "$PROJECT_ROOT/.env" ]]; then
  echo "run.sh: no .env at the root — copy example.env and fill in GEMINI_API_KEY," \
       "or the pipeline will fail when a recording is processed" >&2
fi

# The address the settings resolve to, which is the file and the environment
# layered as the application layers them. It is asked of the application
# rather than reimplemented here; a checkout that cannot answer — a broken
# config file, say — falls back to the defaults and lets uvicorn report it.
if [[ -z "$HOST" || -z "$PORT" ]]; then
  configured="$(cd "$PROJECT_ROOT" && PYTHONPATH="$PROJECT_ROOT/src" poetry run python -c \
    'from config import settings; print(settings.server.host, settings.server.port)' 2>/dev/null || true)"
  read -r CONFIG_HOST CONFIG_PORT <<<"$configured"
  HOST="${HOST:-${CONFIG_HOST:-$FALLBACK_HOST}}"
  PORT="${PORT:-${CONFIG_PORT:-$FALLBACK_PORT}}"
fi

say "Serving on http://$HOST:$PORT"
cd "$PROJECT_ROOT"
# `${RELOAD[@]+...}` and not a plain expansion: under `set -u` the bash that
# ships with macOS calls an empty array unbound.
exec poetry run uvicorn backend:app --app-dir src \
  --host "$HOST" --port "$PORT" ${RELOAD[@]+"${RELOAD[@]}"}
