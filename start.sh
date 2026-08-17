#!/bin/sh
export PYTHONUNBUFFERED=1
export PYTHONPATH="$(pwd)/src:${PYTHONPATH}"

# Start Celery worker in background with explicit working directory
celery -A agent47.infra.queue --workdir src worker --loglevel=info --without-mingle --without-gossip &

# Start Uvicorn web server in foreground with explicit app directory
exec uvicorn agent47.main:app --app-dir src --host 0.0.0.0 --port "${PORT:-8000}"



