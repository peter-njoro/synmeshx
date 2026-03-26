"""
Trust management routes for the Contexa Local API.

Endpoints:
  GET    /trust                  — list trusted devices
  POST   /trust                  — add a trusted device
  DELETE /trust/{device_id}      — revoke a trusted device
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from contexa.store.trust_store import (
    TrustStore,
    TrustEntry,
    DeviceAlreadyTrustedError,
    DeviceNotFoundError,
)

router = APIRouter()


class TrustEntryResponse(BaseModel):
    device_id: str
    public_key_hex: str
    label: str | None
    trusted_at: str
    revoked: bool


class AddTrustRequest(BaseModel):
    device_id: str
    public_key_hex: str   # hex-encoded 32-byte Ed25519 public key
    label: str | None = None


def _get_trust_store(request: Request) -> TrustStore:
    return request.app.state.trust_store


def _entry_to_response(entry: TrustEntry) -> TrustEntryResponse:
    return TrustEntryResponse(
        device_id=entry.device_id,
        public_key_hex=entry.public_key_bytes.hex(),
        label=entry.label,
        trusted_at=entry.trusted_at.isoformat(),
        revoked=entry.revoked,
    )


@router.get("/trust", response_model=list[TrustEntryResponse])
def list_trusted(trust_store: TrustStore = Depends(_get_trust_store)):
    """List all non-revoked trusted devices."""
    return [_entry_to_response(e) for e in trust_store.list_trusted()]


@router.post("/trust", status_code=201, response_model=TrustEntryResponse)
def add_trusted(
    body: AddTrustRequest,
    trust_store: TrustStore = Depends(_get_trust_store),
):
    """Add a device to the trust store."""
    try:
        public_key_bytes = bytes.fromhex(body.public_key_hex)
    except ValueError:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={"error": "validation_error", "detail": "public_key_hex must be valid hex"},
        )

    entry = trust_store.add_trusted(body.device_id, public_key_bytes, body.label)
    return _entry_to_response(entry)


@router.delete("/trust/{device_id}", status_code=204)
def remove_trusted(
    device_id: str,
    trust_store: TrustStore = Depends(_get_trust_store),
):
    """Revoke trust for a device."""
    trust_store.remove_trusted(device_id)
