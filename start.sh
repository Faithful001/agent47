#!/bin/sh
export PYTHONUNBUFFERED=1

# Resolve the absolute path to src/ relative to this script's location
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}/src:${PYTHONPATH}"

echo "PYTHONPATH=${PYTHONPATH}"
echo "Working directory: $(pwd)"
ls -la "${SCRIPT_DIR}/src/agent47/" 2>/dev/null || echo "WARNING: agent47 package not found at ${SCRIPT_DIR}/src/agent47/"

# Start Celery worker in background
celery -A agent47.infra.queue worker --loglevel=info --without-mingle --without-gossip &

# Start Uvicorn web server in foreground
exec uvicorn agent47.main:app --host 0.0.0.0 --port "${PORT:-8000}"

