#!/bin/sh
export PYTHONUNBUFFERED=1
export GIT_PYTHON_REFRESH=quiet

# Automatically install git binary at container boot if missing
if ! command -v git >/dev/null 2>&1; then
    echo "git binary not found in container. Attempting automatic installation..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y -qq git || echo "apt install git failed"
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache git || echo "apk install git failed"
    fi
fi

# Resolve the absolute path to src/ relative to this script's location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH}"

echo "PYTHONPATH=${PYTHONPATH}"
echo "Working directory: $(pwd)"
echo "Git location: $(which git 2>/dev/null || echo 'not found')"
ls -la "${SCRIPT_DIR}/src/agent47/" 2>/dev/null || echo "WARNING: agent47 package not found at ${SCRIPT_DIR}/src/agent47/"

# Start Celery worker in background
celery -A agent47.infra.queue worker --loglevel=info --without-mingle --without-gossip &

# Start Uvicorn web server in foreground
exec uvicorn agent47.main:app --host 0.0.0.0 --port "${PORT:-8000}"


