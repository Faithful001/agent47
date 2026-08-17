#!/bin/sh
export PYTHONUNBUFFERED=1

# Start Celery worker in background
celery -A agent47.infra.queue worker --loglevel=info --without-mingle --without-gossip &

# Start Uvicorn web server in foreground
exec uvicorn agent47.main:app --host 0.0.0.0 --port "${PORT:-8000}"


