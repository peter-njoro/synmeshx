"""
Health, metrics, and config routes for the Contexa Local API.

Endpoints:
  GET /health   — component status
  GET /metrics  — operational counters
  GET /config   — resolved configuration
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Request

from contexa.api.schemas import (
    ComponentStatus,
    HealthResponse,
    MetricsResponse,
    ResolvedConfigResponse,
)

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
def health(request: Request):
    """Return the health status of each daemon subsystem."""
    # Context store: attempt a lightweight list to confirm it's responsive
    try:
        request.app.state.context_store.list_all()
        store_status = ComponentStatus(status="ok")
    except Exception as exc:
        store_status = ComponentStatus(status="error", detail=str(exc))

    # Sync engine and trust store: check presence on app state
    sync_ok = hasattr(request.app.state, "sync_engine")
    trust_ok = hasattr(request.app.state, "trust_store")

    overall = "ok" if (store_status.status == "ok" and sync_ok and trust_ok) else "degraded"

    return HealthResponse(
        status=overall,
        context_store=store_status,
        sync_engine=ComponentStatus(status="ok" if sync_ok else "error"),
        trust_store=ComponentStatus(status="ok" if trust_ok else "error"),
    )


@router.get("/metrics", response_model=MetricsResponse)
def metrics(request: Request):
    """Return basic operational counters."""
    state = request.app.state
    contexts_stored = len(state.context_store.list_all())
    uptime = time.time() - state.start_time

    return MetricsResponse(
        contexts_stored=contexts_stored,
        syncs_completed=getattr(state, "syncs_completed", 0),
        sync_failures=getattr(state, "sync_failures", 0),
        uptime_seconds=round(uptime, 2),
    )


@router.get("/config", response_model=ResolvedConfigResponse)
def config(request: Request):
    """Return the fully resolved configuration including defaults."""
    cfg = request.app.state.config
    return ResolvedConfigResponse(
        daemon_port=cfg.daemon.port,
        daemon_socket_path=cfg.daemon.socket_path,
        daemon_log_level=cfg.daemon.log_level,
        daemon_log_output=cfg.daemon.log_output,
        storage_data_dir=str(cfg.storage.data_dir),
        sync_mode=cfg.sync.mode,
        sync_interval_seconds=cfg.sync.interval_seconds,
        sync_max_retries=cfg.sync.max_retries,
        sync_backoff_base_seconds=cfg.sync.backoff_base_seconds,
        relay_endpoint=cfg.relay.endpoint,
        embeddings_model=cfg.embeddings.model,
    )
