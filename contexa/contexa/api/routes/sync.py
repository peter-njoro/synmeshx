"""
Sync routes for the Contexa Local API.

Endpoints:
  GET  /sync/log     — query the sync log with optional filters
  POST /sync/trigger — trigger a manual sync cycle
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

router = APIRouter()


class SyncLogEntryResponse(BaseModel):
    log_id: str
    device_id: str
    context_id: str
    version_tag: str
    status: str
    error_msg: Optional[str] = None
    created_at: str


def _get_engine(request: Request):
    return request.app.state.sync_engine


@router.get("/sync/log", response_model=list[SyncLogEntryResponse])
def get_sync_log(
    request: Request,
    device_id: Optional[str] = Query(None),
    context_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="ISO-8601 datetime"),
):
    """Query the sync log with optional filters."""
    engine = _get_engine(request)

    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=400,
                content={"error": "validation_error", "detail": "since must be ISO-8601"},
            )

    entries = engine.get_sync_log(
        device_id=device_id,
        context_id=context_id,
        status=status,
        since=since_dt,
    )

    return [
        SyncLogEntryResponse(
            log_id=e.log_id,
            device_id=e.device_id,
            context_id=e.context_id,
            version_tag=e.version_tag,
            status=e.status,
            error_msg=e.error_msg,
            created_at=e.created_at.isoformat() if hasattr(e.created_at, "isoformat") else str(e.created_at),
        )
        for e in entries
    ]


@router.post("/sync/trigger", status_code=202)
async def trigger_sync(request: Request):
    """Trigger a manual sync cycle. Returns 202 Accepted immediately.

    Sets the daemon sync loop's trigger event so it runs a cycle now instead of
    waiting for the next interval. If no sync loop is running (e.g. local-only
    mode or an unauthenticated device), reports that sync is unavailable.
    """
    trigger = getattr(request.app.state, "sync_trigger", None)
    if trigger is None:
        return {"status": "unavailable", "message": "Sync loop is not running"}

    trigger.set()
    return {"status": "accepted", "message": "Sync cycle triggered"}
