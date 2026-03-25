"""
Pydantic request/response schemas for the Contexa Local API.

These are the shapes the API accepts and returns — separate from the
internal ContextStore dataclasses so the API contract can evolve
independently of the storage layer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Context schemas
# ---------------------------------------------------------------------------

class ContextCreateRequest(BaseModel):
    """Body for POST /contexts."""
    content: dict[str, Any] = Field(..., description="Arbitrary JSON payload")
    label: str | None = Field(None, description="Optional human-readable label")


class ContextUpdateRequest(BaseModel):
    """Body for PUT /contexts/{context_id}."""
    content: dict[str, Any] = Field(..., description="New content payload")


class LabelUpdateRequest(BaseModel):
    """Body for PATCH /contexts/{context_id}/label."""
    label: str | None = Field(None, description="New label, or null to clear")


class ContextVersionResponse(BaseModel):
    """Full context version returned by create, get, and update endpoints."""
    version_id: str
    context_id: str
    version_tag: str
    parent_version: str | None
    content: dict[str, Any]
    checksum: str
    created_at: datetime
    label: str | None = None


class ContextSummaryResponse(BaseModel):
    """Lightweight context summary returned by list endpoint."""
    context_id: str
    latest_version_tag: str
    checksum: str
    created_at: datetime
    label: str | None = None


# ---------------------------------------------------------------------------
# Health / metrics / config schemas
# ---------------------------------------------------------------------------

class ComponentStatus(BaseModel):
    status: str          # "ok" | "error"
    detail: str | None = None


class HealthResponse(BaseModel):
    """Response for GET /health."""
    status: str          # "ok" | "degraded"
    context_store: ComponentStatus
    sync_engine: ComponentStatus
    trust_store: ComponentStatus


class MetricsResponse(BaseModel):
    """Response for GET /metrics."""
    contexts_stored: int
    syncs_completed: int
    sync_failures: int
    uptime_seconds: float


class ResolvedConfigResponse(BaseModel):
    """Response for GET /config — the fully resolved configuration."""
    daemon_port: int
    daemon_socket_path: str
    daemon_log_level: str
    daemon_log_output: str
    storage_data_dir: str
    sync_mode: str
    sync_interval_seconds: int
    sync_max_retries: int
    sync_backoff_base_seconds: int
    relay_endpoint: str
    embeddings_model: str


# ---------------------------------------------------------------------------
# Error schemas
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    """Standard error envelope returned on 4xx/5xx responses."""
    error: str
    detail: Any = None
