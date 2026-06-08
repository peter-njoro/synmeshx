"""
Context_Store: local SQLite-backed store for versioned Context objects.

Handles create, read, list, delete, checksum verification, and label updates.
All content writes produce a new immutable ContextVersion row — existing
versions are never mutated. Labels are mutable metadata stored on the
contexts row and do not trigger a new version.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from contexa.store.models import ContextRecord, ContextVersionRecord


# Exceptions

class NotFoundError(Exception):
    """Raised when a requested Context_ID or Version_Tag does not exist."""

    def __init__(self, context_id: str, version_tag: str | None = None) -> None:
        self.context_id = context_id
        self.version_tag = version_tag
        if version_tag:
            super().__init__(f"Context '{context_id}' version '{version_tag}' not found")
        else:
            super().__init__(f"Context '{context_id}' not found")


class ChecksumError(Exception):
    """Raised when a stored checksum does not match the content on read."""

    def __init__(self, context_id: str, version_tag: str) -> None:
        self.context_id = context_id
        self.version_tag = version_tag
        super().__init__(
            f"Checksum mismatch for context '{context_id}' version '{version_tag}' — "
            "data may be corrupted"
        )


# Data transfer objects

@dataclass
class ContextVersion:
    """A single immutable snapshot of a context."""
    version_id: str
    context_id: str
    version_tag: str
    parent_version: str | None
    content: dict[str, Any]
    checksum: str
    created_at: datetime
    label: str | None = None


@dataclass
class ContextSummary:
    """Lightweight summary of a context — latest version only."""
    context_id: str
    latest_version_tag: str
    checksum: str
    created_at: datetime
    label: str | None = None


# Helpers

def _compute_checksum(content: dict[str, Any]) -> str:
    """Compute SHA-256 of the canonical JSON representation of content."""
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _new_id() -> str:
    return str(uuid.uuid4())


def _version_tag_from_id(version_id: str) -> str:
    """Derive a short version tag from a UUID (first 8 hex chars)."""
    return version_id.replace("-", "")[:8]


def _record_to_version(record: ContextVersionRecord, label: str | None) -> ContextVersion:
    return ContextVersion(
        version_id=record.version_id,
        context_id=record.context_id,
        version_tag=record.version_tag,
        parent_version=record.parent_version,
        content=json.loads(record.content),
        checksum=record.checksum,
        created_at=record.created_at,
        label=label,
    )


# Context_Store

class ContextStore:
    """Manages all reads and writes to the contexts and context_versions tables."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # Write operations

    def create(
        self,
        content: dict[str, Any],
        owner_device: str,
        label: str | None = None,
    ) -> ContextVersion:
        """Create a new context with an initial version.

        Args:
            content: Arbitrary JSON-serialisable dict — the context payload.
            owner_device: Device_ID of the device creating this context.
            label: Optional human-readable label (mutable metadata).

        Returns:
            The newly created ContextVersion.
        """
        context_id = _new_id()
        version_id = _new_id()
        version_tag = _version_tag_from_id(version_id)
        checksum = _compute_checksum(content)

        ctx = ContextRecord(
            context_id=context_id,
            owner_device=owner_device,
            label=label,
        )
        version = ContextVersionRecord(
            version_id=version_id,
            context_id=context_id,
            version_tag=version_tag,
            parent_version=None,
            content=json.dumps(content, sort_keys=True),
            checksum=checksum,
        )

        self._session.add(ctx)
        self._session.add(version)
        self._session.commit()
        self._session.refresh(version)

        return _record_to_version(version, label)

    def update(
        self,
        context_id: str,
        content: dict[str, Any],
    ) -> ContextVersion:
        """Write a new version of an existing context.

        Creates a new immutable ContextVersion row — the previous version
        is never modified. The new version's parent_version points to the
        previous latest version_id.

        Args:
            context_id: UUID of the context to update.
            content: New content payload.

        Returns:
            The newly created ContextVersion.

        Raises:
            NotFoundError: If context_id does not exist.
        """
        ctx = self._session.get(ContextRecord, context_id)
        if ctx is None:
            raise NotFoundError(context_id)

        # Find the current latest version to set as parent
        latest = self._get_latest_version_record(context_id)
        parent_version_id = latest.version_id if latest else None

        version_id = _new_id()
        version_tag = _version_tag_from_id(version_id)
        checksum = _compute_checksum(content)

        version = ContextVersionRecord(
            version_id=version_id,
            context_id=context_id,
            version_tag=version_tag,
            parent_version=parent_version_id,
            content=json.dumps(content, sort_keys=True),
            checksum=checksum,
        )

        self._session.add(version)
        self._session.commit()
        self._session.refresh(version)

        return _record_to_version(version, ctx.label)

    def update_label(self, context_id: str, label: str | None) -> ContextSummary:
        """Update the label on a context WITHOUT creating a new version.

        Labels are mutable metadata — they do not affect versioning or sync.

        Args:
            context_id: UUID of the context to relabel.
            label: New label string, or None to clear it.

        Returns:
            Updated ContextSummary.

        Raises:
            NotFoundError: If context_id does not exist.
        """
        ctx = self._session.get(ContextRecord, context_id)
        if ctx is None:
            raise NotFoundError(context_id)

        ctx.label = label
        self._session.commit()

        latest = self._get_latest_version_record(context_id)
        return ContextSummary(
            context_id=context_id,
            latest_version_tag=latest.version_tag if latest else "",
            checksum=latest.checksum if latest else "",
            created_at=ctx.created_at,
            label=ctx.label,
        )

    def delete(self, context_id: str) -> None:
        """Delete a context and all its versions.

        Args:
            context_id: UUID of the context to delete.

        Raises:
            NotFoundError: If context_id does not exist.
        """
        ctx = self._session.get(ContextRecord, context_id)
        if ctx is None:
            raise NotFoundError(context_id)

        self._session.delete(ctx)
        self._session.commit()

    # Read operations

    def get(
        self,
        context_id: str,
        version_tag: str | None = None,
    ) -> ContextVersion:
        """Retrieve a context version.

        Args:
            context_id: UUID of the context.
            version_tag: Specific version to retrieve. If None, returns latest.

        Returns:
            The requested ContextVersion.

        Raises:
            NotFoundError: If context_id or version_tag does not exist.
            ChecksumError: If the stored checksum does not match the content.
        """
        ctx = self._session.get(ContextRecord, context_id)
        if ctx is None:
            raise NotFoundError(context_id)

        if version_tag is None:
            record = self._get_latest_version_record(context_id)
            if record is None:
                raise NotFoundError(context_id)
        else:
            record = (
                self._session.query(ContextVersionRecord)
                .filter_by(context_id=context_id, version_tag=version_tag)
                .first()
            )
            if record is None:
                raise NotFoundError(context_id, version_tag)

        self.verify_checksum(record)
        return _record_to_version(record, ctx.label)

    def list_all(self) -> list[ContextSummary]:
        """List all contexts with their latest version summary.

        Returns:
            List of ContextSummary objects, one per context.
        """
        contexts = self._session.query(ContextRecord).all()
        summaries = []
        for ctx in contexts:
            latest = self._get_latest_version_record(ctx.context_id)
            summaries.append(ContextSummary(
                context_id=ctx.context_id,
                latest_version_tag=latest.version_tag if latest else "",
                checksum=latest.checksum if latest else "",
                created_at=ctx.created_at,
                label=ctx.label,
            ))
        return summaries

    def list_versions(self, context_id: str) -> list[ContextVersion]:
        """List all versions of a context in chronological order.

        Args:
            context_id: UUID of the context.

        Returns:
            List of ContextVersion objects ordered oldest → newest.

        Raises:
            NotFoundError: If context_id does not exist.
        """
        ctx = self._session.get(ContextRecord, context_id)
        if ctx is None:
            raise NotFoundError(context_id)

        records = (
            self._session.query(ContextVersionRecord)
            .filter_by(context_id=context_id)
            .order_by(ContextVersionRecord.created_at)
            .all()
        )
        return [_record_to_version(r, ctx.label) for r in records]

    # Integrity

    def verify_checksum(self, record: ContextVersionRecord) -> bool:
        """Verify the stored checksum matches the content.

        Args:
            record: The ContextVersionRecord to verify.

        Returns:
            True if the checksum is valid.

        Raises:
            ChecksumError: If the checksum does not match.
        """
        content = json.loads(record.content)
        expected = _compute_checksum(content)
        if record.checksum != expected:
            raise ChecksumError(record.context_id, record.version_tag)
        return True

    # Internal helpers

    def _get_latest_version_record(
        self, context_id: str
    ) -> ContextVersionRecord | None:
        """Return the most recently created version record for a context."""
        return (
            self._session.query(ContextVersionRecord)
            .filter_by(context_id=context_id)
            .order_by(ContextVersionRecord.created_at.desc())
            .first()
        )
