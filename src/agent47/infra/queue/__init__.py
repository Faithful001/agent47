import os
from celery import Celery

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6380/0")

celery = Celery(
    'agent47_tasks',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "src.infra.queue.tasks.run_ci_task",
        "src.infra.queue.tasks.run_pipeline",
    ]
)