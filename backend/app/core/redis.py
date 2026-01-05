import redis.asyncio as redis
from contextlib import asynccontextmanager
from fastapi import FastAPI
from .config import settings

REDIS_URL = f"redis://synmeshx_redis:{settings.redis_port}"

redis_client: redis.Redis | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global redis_client
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis_client.ping()
        print("Connected to Redis")
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")
    yield
    if redis_client:
        await redis_client.close()
        print("Disconnected from Redis")
