"""
Trust_Store: local registry of trusted peer devices.

Backed by the `devices` and `trust_entries` SQLite tables.
A device is trusted if it has a non-revoked TrustEntry.
Revocation sets revoked=True rather than deleting, preserving audit history.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from contexa.store.models import DeviceRecord, TrustEntryRecord
from contexa.sync.crypto import (
    DeviceIdentity,
    load_or_generate_identity,
    public_key_from_bytes,
)


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------

@dataclass
class TrustEntry:
    """A trusted peer device."""
    device_id: str
    public_key_bytes: bytes
    label: str | None
    trusted_at: datetime
    revoked: bool


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class DeviceNotFoundError(Exception):
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"Device '{device_id}' not found in trust store")


class DeviceAlreadyTrustedError(Exception):
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        super().__init__(f"Device '{device_id}' is already trusted")


# ---------------------------------------------------------------------------
# TrustStore
# ---------------------------------------------------------------------------

class TrustStore:
    """Manages the local registry of trusted devices."""

    def __init__(self, session: Session, data_dir: Path | None = None) -> None:
        self._session = session
        self._data_dir = Path(data_dir or "~/.local/share/contexa").expanduser()
        self._identity: DeviceIdentity | None = None

    # ------------------------------------------------------------------
    # Self registration
    # ------------------------------------------------------------------

    def register_self(self) -> DeviceIdentity:
        """Load or generate this device's identity and register it in the DB.

        Safe to call on every startup — idempotent if already registered.

        Returns:
            The loaded or newly generated DeviceIdentity.
        """
        identity = load_or_generate_identity(self._data_dir)
        self._identity = identity

        # Upsert the self device record
        existing = self._session.get(DeviceRecord, identity.device_id)
        if existing is None:
            record = DeviceRecord(
                device_id=identity.device_id,
                public_key=identity.public_key_bytes(),
            )
            self._session.add(record)
            self._session.commit()

        return identity

    @property
    def identity(self) -> DeviceIdentity:
        """Return the loaded device identity. Call register_self() first."""
        if self._identity is None:
            raise RuntimeError("TrustStore.register_self() has not been called")
        return self._identity

    # ------------------------------------------------------------------
    # Trust management
    # ------------------------------------------------------------------

    def add_trusted(
        self,
        device_id: str,
        public_key_bytes: bytes,
        label: str | None = None,
    ) -> TrustEntry:
        """Add a device to the trust store.

        Args:
            device_id: UUID of the peer device.
            public_key_bytes: Raw 32-byte Ed25519 public key.
            label: Optional human-readable name for this device.

        Returns:
            The created TrustEntry.

        Raises:
            DeviceAlreadyTrustedError: If the device is already trusted (not revoked).
        """
        existing = self._session.get(DeviceRecord, device_id)

        if existing is not None:
            trust = self._session.get(TrustEntryRecord, device_id)
            if trust is not None and not trust.revoked:
                raise DeviceAlreadyTrustedError(device_id)
            if trust is not None and trust.revoked:
                # Re-trust a previously revoked device
                trust.revoked = False
                trust.label = label
                trust.trusted_at = datetime.now(timezone.utc)
                self._session.commit()
                return _record_to_entry(existing, trust)
        else:
            # Validate the public key is parseable
            public_key_from_bytes(public_key_bytes)
            device = DeviceRecord(
                device_id=device_id,
                public_key=public_key_bytes,
            )
            self._session.add(device)

        trust = TrustEntryRecord(
            device_id=device_id,
            label=label,
            revoked=False,
        )
        self._session.add(trust)
        self._session.commit()

        device_record = self._session.get(DeviceRecord, device_id)
        return _record_to_entry(device_record, trust)

    def remove_trusted(self, device_id: str) -> None:
        """Revoke trust for a device (sets revoked=True, does not delete).

        Args:
            device_id: UUID of the device to revoke.

        Raises:
            DeviceNotFoundError: If the device is not in the trust store.
        """
        trust = self._session.get(TrustEntryRecord, device_id)
        if trust is None:
            raise DeviceNotFoundError(device_id)

        trust.revoked = True
        self._session.commit()

    def is_trusted(self, device_id: str) -> bool:
        """Return True if the device has a non-revoked trust entry."""
        trust = self._session.get(TrustEntryRecord, device_id)
        return trust is not None and not trust.revoked

    def list_trusted(self) -> list[TrustEntry]:
        """Return all non-revoked trusted devices."""
        entries = (
            self._session.query(TrustEntryRecord)
            .filter_by(revoked=False)
            .all()
        )
        result = []
        for trust in entries:
            device = self._session.get(DeviceRecord, trust.device_id)
            if device:
                result.append(_record_to_entry(device, trust))
        return result

    def get_public_key(self, device_id: str) -> bytes:
        """Return the raw public key bytes for a device.

        Raises:
            DeviceNotFoundError: If the device is not registered.
        """
        device = self._session.get(DeviceRecord, device_id)
        if device is None:
            raise DeviceNotFoundError(device_id)
        return device.public_key


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _record_to_entry(device: DeviceRecord, trust: TrustEntryRecord) -> TrustEntry:
    return TrustEntry(
        device_id=device.device_id,
        public_key_bytes=device.public_key,
        label=trust.label,
        trusted_at=trust.trusted_at,
        revoked=trust.revoked,
    )
