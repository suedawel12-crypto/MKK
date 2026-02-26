import redis.asyncio as redis
import json
from typing import Optional, Any
import asyncio
from datetime import timedelta

from config import settings

class RedisClient:
    def __init__(self):
        self.redis_url = settings.REDIS_URL
        self.client = None
        
    async def connect(self):
        self.client = await redis.from_url(
            self.redis_url,
            decode_responses=True,
            max_connections=50
        )
        return self.client
    
    async def get_client(self):
        if not self.client:
            await self.connect()
        return self.client
    
    # Locking mechanism
    async def acquire_lock(self, lock_name: str, timeout: int = 10) -> bool:
        client = await self.get_client()
        return await client.set(
            f"lock:{lock_name}",
            "locked",
            nx=True,
            ex=timeout
        )
    
    async def release_lock(self, lock_name: str):
        client = await self.get_client()
        await client.delete(f"lock:{lock_name}")
    
    # Rate limiting
    async def check_rate_limit(self, key: str, max_calls: int, period: int) -> bool:
        client = await self.get_client()
        current = await client.incr(f"rate:{key}")
        if current == 1:
            await client.expire(f"rate:{key}", period)
        return current <= max_calls
    
    # Pub/Sub
    async def publish(self, channel: str, message: Any):
        client = await self.get_client()
        await client.publish(channel, json.dumps(message))
    
    # Cache
    async def set_cache(self, key: str, value: Any, expire: int = 300):
        client = await self.get_client()
        await client.setex(f"cache:{key}", expire, json.dumps(value))
    
    async def get_cache(self, key: str) -> Optional[Any]:
        client = await self.get_client()
        data = await client.get(f"cache:{key}")
        return json.loads(data) if data else None

redis_client = RedisClient()