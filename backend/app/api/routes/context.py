from fastapi import APIRouter, Depends
from app.utils.redis_utils import cache_mesh_context, publish_mesh_update
from app.models import Context
from sqlalchemy.orm import Session
from app.core.database import get_db

router = APIRouter()

@router.post("/contexts/{project_id}")
async def update_context(project_id: str, payload: dict, db: Session = Depends(get_db)):
    # Assume payload includes mesh update
    context = Context.create_from_payload(project_id, payload)
    db.add(context)
    db.commit()

    # Cache it for fast access
    await cache_mesh_context(str(context.id), payload)

    # Publish real-time update to all connected agents
    await publish_mesh_update(project_id, {
        "event": "context_updated",
        "context_id": str(context.id),
        "version_tag": payload.get("version_tag"),
    })

    return {"status": "ok", "context_id": context.id}
