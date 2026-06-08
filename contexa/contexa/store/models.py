"""
SQLAlchemy ORM models for Contexa's local SQLite database.

Tables:
  - contexts          : top-level context records (one per logical context)
  - context_versions  : immutable versioned snapshots of context content
  - devices           : known devices (self + trusted peers)
  - trust_entries     : trust registry — which devices are authorised to sync
  - sync_log          : audit log of every sync operation
  - embeddings        : vector embeddings for semantic search
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from contexa.store.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# Context tables

class ContextRecord(Base):
    """Top-level context record.

    One row per logical context. The actual content lives in ContextVersion.
    The label is mutable metadata — updating it does NOT create a new version.
    """

    __tablename__ = "contexts"

    context_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    owner_device: Mapped[str] = mapped_column(String(36), nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)

    versions: Mapped[list[ContextVersionRecord]] = relationship(
        "ContextVersionRecord",
        back_populates="context",
        cascade="all, delete-orphan",
        order_by="ContextVersionRecord.created_at",
    )


class ContextVersionRecord(Base):
    """Immutable snapshot of a context at a point in time.

    Every write to a context creates a new row here — existing rows are
    never mutated. parent_version links versions into a history chain,
    enabling ancestor-based conflict detection during sync.
    """

    __tablename__ = "context_versions"
    __table_args__ = (
        UniqueConstraint("context_id", "version_tag", name="uq_context_version_tag"),
    )

    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    context_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contexts.context_id", ondelete="CASCADE"), nullable=False
    )
    version_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    parent_version: Mapped[str | None] = mapped_column(String(36), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)       # JSON blob
    checksum: Mapped[str] = mapped_column(String(64), nullable=False) # SHA-256 hex
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    context: Mapped[ContextRecord] = relationship(
        "ContextRecord", back_populates="versions"
    )


# Device identity and trust

class DeviceRecord(Base):
    """A known device — either this device (self) or a trusted peer.

    public_key stores the raw Ed25519 public key bytes.
    identity_id is the OAuth subject that links devices to a single user.
    """

    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    identity_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    trust_entry: Mapped[TrustEntryRecord | None] = relationship(
        "TrustEntryRecord", back_populates="device", uselist=False
    )


class TrustEntryRecord(Base):
    """Trust registry entry for a peer device.

    A device is trusted if it has a non-revoked entry here.
    revoked=True means the device was previously trusted but has been removed.
    """

    __tablename__ = "trust_entries"

    device_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("devices.device_id", ondelete="CASCADE"), primary_key=True
    )
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    trusted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    device: Mapped[DeviceRecord] = relationship(
        "DeviceRecord", back_populates="trust_entry"
    )


# Sync log

class SyncLogRecord(Base):
    """Audit record for a single sync operation.

    status is one of: 'success' | 'conflict' | 'failed' | 'pending'
    """

    __tablename__ = "sync_log"

    log_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False)
    context_id: Mapped[str] = mapped_column(String(36), nullable=False)
    version_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )


# Embeddings

class EmbeddingRecord(Base):
    """Vector embedding for a specific context version.

    vector stores a serialised numpy float32 array (numpy.ndarray.tobytes()).
    model_name records which sentence-transformers model produced the vector,
    so embeddings can be invalidated if the model changes.
    """

    __tablename__ = "embeddings"

    embedding_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    context_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("contexts.context_id", ondelete="CASCADE"), nullable=False
    )
    version_tag: Mapped[str] = mapped_column(String(64), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
