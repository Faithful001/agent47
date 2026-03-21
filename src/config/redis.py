import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI
from redis.asyncio import ConnectionPool, Redis, from_url

REDIS_URL = os.getenv("REDIS_URL") or "redis://localhost:6379/0"

_pool: ConnectionPool | None = None

def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=20,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
    return _pool


async def get_redis() -> AsyncGenerator[Redis, None]:
    pool = get_redis_pool()
    client = Redis(connection_pool=pool)
    try:
        yield client
    finally:
        pass


@asynccontextmanager
async def redis_lifespan(app: FastAPI):
    pool = get_redis_pool()
    async with Redis(connection_pool=pool) as r:
        await r.ping()
    yield