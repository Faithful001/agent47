import json
import asyncio
from typing import Callable, Awaitable
from redis.asyncio import Redis

class PubSubManager:
    def __init__(self, redis: Redis):
        self.redis = redis
        self.subscribers: dict[str, set[Callable[[dict], Awaitable[None]]]] = {}

    async def publish(self, channel: str, message: dict):
        """Publish a JSON message to a channel"""
        await self.redis.publish(channel, json.dumps(message)) # convert the message dict to a json format

    async def subscribe(self, channel: str, callback: Callable[[dict], Awaitable[None]]):
        """Subscribe to a channel and call callback on messages"""
        if channel not in self.subscribers:
            self.subscribers[channel] = set()
        self.subscribers[channel].add(callback)

        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)

        async def listener():
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        data = json.loads(message["data"])
                        await callback(data)
                    except Exception as e:
                        print(f"PubSub error: {e}")

        asyncio.create_task(listener())

    async def unsubscribe(self, channel: str, callback: Callable):
        if channel in self.subscribers:
            self.subscribers[channel].discard(callback)
            if not self.subscribers[channel]:
                del self.subscribers[channel]