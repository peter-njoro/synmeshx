import asyncio
import json
from app.core.redis import redis_client

async def listen_to_mesh_updates(project_id: str):
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"mesh:updates:{project_id}")

    async for message in pubsub.listen():
        if message['type'] == 'message':
            data = json.loads(message['data'])
            print(f"Received mesh update for project {project_id}: {data}")
            # Here you would typically forward this update to connected clients,
            # e.g., via WebSocket or another real-time mechanism.
            # For demonstration, we just print it.
            # Example: await websocket_manager.broadcast_to_project(project_id, data)
            # Simulate processing time
            await asyncio.sleep(0.1)
async def start_mesh_listener(project_ids: list[str]):
    if not redis_client:
        print("Redis client is not initialized.")
        return

    listeners = [listen_to_mesh_updates(pid) for pid in project_ids]
    await asyncio.gather(*listeners)
# Example usage:
# asyncio.run(start_mesh_listener(['project1', 'project2']))    
