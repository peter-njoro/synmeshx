"""
Context CRUD routes for the Contexa Local API.

Endpoints:
  POST   /contexts
  GET    /contexts
  GET    /contexts/{context_id}
  GET    /contexts/{context_id}/versions/{version_tag}
  PUT    /contexts/{context_id}
  PATCH  /contexts/{context_id}/label
  DELETE /contexts/{context_id}
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from contexa.api.schemas import (
    ContextCreateRequest,
    ContextSummaryResponse,
    ContextUpdateRequest,
    ContextVersionResponse,
    LabelUpdateRequest,
)
from contexa.store.context_store import ContextStore, NotFoundError, ChecksumError
from contexa.store.embedding_store import EmbeddingDisabledError

router = APIRouter()


def _get_store(request: Request) -> ContextStore:
    """Dependency: retrieve the ContextStore from app state."""
    return request.app.state.context_store


def _get_embedding_store(request: Request):
    """Dependency: retrieve the EmbeddingStore from app state (may be None)."""
    return getattr(request.app.state, "embedding_store", None)


def _version_to_response(v) -> ContextVersionResponse:
    return ContextVersionResponse(
        version_id=v.version_id,
        context_id=v.context_id,
        version_tag=v.version_tag,
        parent_version=v.parent_version,
        content=v.content,
        checksum=v.checksum,
        created_at=v.created_at,
        label=v.label,
    )


def _summary_to_response(s) -> ContextSummaryResponse:
    return ContextSummaryResponse(
        context_id=s.context_id,
        latest_version_tag=s.latest_version_tag,
        checksum=s.checksum,
        created_at=s.created_at,
        label=s.label,
    )


@router.post("/contexts", status_code=201, response_model=ContextVersionResponse)
def create_context(
    body: ContextCreateRequest,
    request: Request,
    store: ContextStore = Depends(_get_store),
):
    """Create a new context with an initial version."""
    owner = request.app.state.device_id
    v = store.create(body.content, owner_device=owner, label=body.label)
    return _version_to_response(v)


@router.get("/contexts", response_model=list[ContextSummaryResponse])
def list_contexts(store: ContextStore = Depends(_get_store)):
    """List all contexts with their latest version summary."""
    return [_summary_to_response(s) for s in store.list_all()]


# NOTE: /contexts/search MUST be registered before /contexts/{context_id}
# to prevent FastAPI matching "search" as a context_id path parameter.
@router.get("/contexts/search", response_model=list[ContextVersionResponse])
def search_contexts(
    request: Request,
    q: str = Query(..., description="Natural language search query"),
    top_n: int = Query(10, ge=1, le=100),
    store: ContextStore = Depends(_get_store),
):
    """Semantic similarity search over context objects."""
    embedding_store = _get_embedding_store(request)
    if embedding_store is None or not embedding_store.enabled:
        return JSONResponse(
            status_code=503,
            content={"error": "embedding_disabled",
                     "detail": "No embedding model configured. Set [embeddings] model in config.toml."},
        )

    try:
        results = embedding_store.search(q, top_n=top_n)
    except EmbeddingDisabledError:
        return JSONResponse(
            status_code=503,
            content={"error": "embedding_disabled"},
        )

    versions = []
    for context_id, version_tag, _score in results:
        try:
            v = store.get(context_id, version_tag=version_tag)
            versions.append(_version_to_response(v))
        except Exception:
            continue
    return versions


@router.get("/contexts/{context_id}", response_model=ContextVersionResponse)
def get_context(
    context_id: str,
    store: ContextStore = Depends(_get_store),
):
    """Get the latest version of a context."""
    v = store.get(context_id)
    return _version_to_response(v)


@router.get(
    "/contexts/{context_id}/versions/{version_tag}",
    response_model=ContextVersionResponse,
)
def get_context_version(
    context_id: str,
    version_tag: str,
    store: ContextStore = Depends(_get_store),
):
    """Get a specific version of a context by version tag."""
    v = store.get(context_id, version_tag=version_tag)
    return _version_to_response(v)


@router.put("/contexts/{context_id}", response_model=ContextVersionResponse)
def update_context(
    context_id: str,
    body: ContextUpdateRequest,
    store: ContextStore = Depends(_get_store),
):
    """Write a new version of an existing context."""
    v = store.update(context_id, body.content)
    return _version_to_response(v)


@router.patch("/contexts/{context_id}/label", response_model=ContextSummaryResponse)
def update_label(
    context_id: str,
    body: LabelUpdateRequest,
    store: ContextStore = Depends(_get_store),
):
    """Update the label on a context without creating a new version."""
    s = store.update_label(context_id, body.label)
    return _summary_to_response(s)


@router.delete("/contexts/{context_id}", status_code=204)
def delete_context(
    context_id: str,
    store: ContextStore = Depends(_get_store),
):
    """Delete a context and all its versions."""
    store.delete(context_id)
