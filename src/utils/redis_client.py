"""Redis client utilities"""

import redis.asyncio as aioredis
from typing import Optional, List
from loguru import logger
from src.config.settings import settings


class RedisClient:
    """Redis async client manager"""
    
    def __init__(self):
        self.client: Optional[aioredis.Redis] = None
    
    async def connect(self):
        """Create Redis connection"""
        try:
            self.client = await aioredis.from_url(
                f"redis://{settings.redis_host}:{settings.redis_port}/{settings.redis_db}",
                password=settings.redis_password,
                encoding="utf-8",
                decode_responses=True,
            )
            await self.client.ping()
            logger.info("Redis connection established")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    
    async def disconnect(self):
        """Close Redis connection"""
        if self.client:
            await self.client.close()
            logger.info("Redis connection closed")
    
    async def get(self, key: str) -> Optional[str]:
        """Get value by key"""
        return await self.client.get(key)
    
    async def set(self, key: str, value: str, ex: Optional[int] = None):
        """Set key-value pair with optional expiration"""
        await self.client.set(key, value, ex=ex)
    
    async def delete(self, key: str):
        """Delete key"""
        await self.client.delete(key)
    
    async def lpush(self, key: str, *values):
        """Push values to list (left)"""
        await self.client.lpush(key, *values)
    
    async def lrange(self, key: str, start: int, end: int) -> List[str]:
        """Get range of list"""
        return await self.client.lrange(key, start, end)
    
    async def ltrim(self, key: str, start: int, end: int):
        """Trim list to specified range"""
        await self.client.ltrim(key, start, end)
    
    async def hset(self, name: str, mapping: dict):
        """Set hash fields"""
        await self.client.hset(name, mapping=mapping)
    
    async def hgetall(self, name: str) -> dict:
        """Get all hash fields"""
        return await self.client.hgetall(name)


# Global Redis client instance
redis_client = RedisClient()
