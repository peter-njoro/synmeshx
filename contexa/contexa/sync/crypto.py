"""
Cryptographic primitives for Contexa device identity and sync security.

Provides:
  - Ed25519 key pair generation, persistence, and loading (device identity + signing)
  - X25519 key exchange (derive shared secret for session encryption)
  - AES-256-GCM encryption/decryption with HKDF-SHA256 session key derivation
  - Ed25519 sign/verify for challenge-response authentication

Key files (stored in data_dir):
  - device_id    : plaintext UUID
  - device_key.pem : Ed25519 private key, PEM format, mode 0600
"""

from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


# Device identity

@dataclass
class DeviceIdentity:
    """The cryptographic identity of this device."""
    device_id: str                    # UUID string
    private_key: Ed25519PrivateKey    # Ed25519 signing key (never leaves device)
    public_key: Ed25519PublicKey      # Ed25519 verification key (shared with peers)

    def public_key_bytes(self) -> bytes:
        """Return the raw public key bytes (32 bytes)."""
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )

    def private_key_pem(self) -> bytes:
        """Return the private key in PEM format (no password)."""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )


def generate_device_identity() -> DeviceIdentity:
    """Generate a new Device_ID and Ed25519 key pair."""
    device_id = str(uuid.uuid4())
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key()
    return DeviceIdentity(
        device_id=device_id,
        private_key=private_key,
        public_key=public_key,
    )


def save_device_identity(identity: DeviceIdentity, data_dir: Path) -> None:
    """Persist Device_ID and private key to data_dir.

    - device_id is written as plaintext
    - device_key.pem is written with mode 0600 (owner read/write only)
    """
    data_dir = Path(data_dir).expanduser()
    data_dir.mkdir(parents=True, exist_ok=True)

    id_file = data_dir / "device_id"
    key_file = data_dir / "device_key.pem"

    id_file.write_text(identity.device_id)

    key_file.write_bytes(identity.private_key_pem())
    key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600


def load_device_identity(data_dir: Path) -> DeviceIdentity:
    """Load Device_ID and private key from data_dir.

    Raises FileNotFoundError if either file is missing.
    """
    data_dir = Path(data_dir).expanduser()
    id_file = data_dir / "device_id"
    key_file = data_dir / "device_key.pem"

    device_id = id_file.read_text().strip()
    pem_bytes = key_file.read_bytes()
    private_key = serialization.load_pem_private_key(pem_bytes, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("device_key.pem does not contain an Ed25519 private key")

    return DeviceIdentity(
        device_id=device_id,
        private_key=private_key,
        public_key=private_key.public_key(),
    )


def load_or_generate_identity(data_dir: Path) -> DeviceIdentity:
    """Load existing identity or generate a new one on first run."""
    data_dir = Path(data_dir).expanduser()
    id_file = data_dir / "device_id"
    key_file = data_dir / "device_key.pem"

    if id_file.exists() and key_file.exists():
        return load_device_identity(data_dir)

    identity = generate_device_identity()
    save_device_identity(identity, data_dir)
    return identity


def public_key_from_bytes(raw_bytes: bytes) -> Ed25519PublicKey:
    """Reconstruct an Ed25519PublicKey from 32 raw bytes."""
    return Ed25519PublicKey.from_public_bytes(raw_bytes)


# Ed25519 signing / verification

def sign(private_key: Ed25519PrivateKey, message: bytes) -> bytes:
    """Sign a message with an Ed25519 private key. Returns 64-byte signature."""
    return private_key.sign(message)


def verify(public_key: Ed25519PublicKey, message: bytes, signature: bytes) -> bool:
    """Verify an Ed25519 signature. Returns True if valid, False otherwise."""
    try:
        public_key.verify(signature, message)
        return True
    except Exception:
        return False


# X25519 key exchange + AES-256-GCM session encryption

def generate_x25519_keypair() -> tuple[X25519PrivateKey, X25519PublicKey]:
    """Generate an ephemeral X25519 key pair for a sync session."""
    private = X25519PrivateKey.generate()
    return private, private.public_key()


def x25519_public_key_bytes(public_key: X25519PublicKey) -> bytes:
    """Return raw 32-byte representation of an X25519 public key."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def x25519_public_key_from_bytes(raw_bytes: bytes) -> X25519PublicKey:
    """Reconstruct an X25519PublicKey from 32 raw bytes."""
    return X25519PublicKey.from_public_bytes(raw_bytes)


def derive_session_key(
    local_private: X25519PrivateKey,
    peer_public: X25519PublicKey,
    nonce: bytes,
    device_id: str,
) -> bytes:
    """Derive a 32-byte AES-256-GCM session key via X25519 + HKDF-SHA256.

    Uses the design's key derivation scheme:
      shared_secret = X25519(local_private, peer_public)
      session_key   = HKDF(shared_secret, salt=nonce, info="contexa-sync-v1")
    """
    shared_secret = local_private.exchange(peer_public)
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=nonce,
        info=b"contexa-sync-v1",
    )
    return hkdf.derive(shared_secret)


def encrypt(session_key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
    """Encrypt plaintext with AES-256-GCM.

    Args:
        session_key: 32-byte key derived from derive_session_key()
        nonce: 12-byte random nonce
        plaintext: data to encrypt
        aad: additional authenticated data (e.g. device_id bytes)

    Returns:
        ciphertext + 16-byte GCM tag (concatenated by cryptography library)
    """
    aesgcm = AESGCM(session_key)
    return aesgcm.encrypt(nonce, plaintext, aad)


def decrypt(session_key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes:
    """Decrypt AES-256-GCM ciphertext.

    Raises cryptography.exceptions.InvalidTag if authentication fails.
    """
    aesgcm = AESGCM(session_key)
    return aesgcm.decrypt(nonce, ciphertext, aad)


def generate_nonce() -> bytes:
    """Generate a cryptographically random 12-byte nonce for AES-GCM."""
    return os.urandom(12)
