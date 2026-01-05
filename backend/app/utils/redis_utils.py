import json
from app.core.redis import redis_client

# Cache a mesh context (auto-expiring after ttl seconds)
async def cache_mesh_context(context_id: str, mesh_data: dict, ttl: int = 3600):
    if not redis_client:
        return
    await redis_client.set(f"mesh:context:{context_id}", json.dumps(mesh_data), ex=ttl)

# Retrieve a cached mesh context
async def get_cached_context(context_id: str):
    if not redis_client:
        return None
    data = await redis_client.get(f"mesh:context:{context_id}")
    return json.loads(data) if data else None

async def publish_mesh_update(project_id: str, event: dict):
    if not redis_client:
        return
    await redis_client.publish(f"mesh:updates:{project_id}", json.dumps(event))

async def with_context_lock(context_id: str, func):
    lock_key = f"lock:context:{context_id}"
    async with redis_client.lock(lock_key, timeout=5):
        await func()

