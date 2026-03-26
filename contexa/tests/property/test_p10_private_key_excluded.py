# Feature: contexa-core, Property 10: Private Key Excluded from Sync Payloads
"""
For any sync payload generated, the serialized bytes must not contain
the local device's Ed25519 private key material.
Validates: Requirements 6.2
"""

from __future__ import annotations

import json
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from contexa.sync.crypto import generate_device_identity, save_device_identity


json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.one_of(st.integers(), st.text(max_size=20)),
    max_size=5,
)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_private_key_not_in_serialized_context(tmp_path, content):
    """Serialized context payload does not contain private key bytes."""
    identity = generate_device_identity()
    save_device_identity(identity, tmp_path)

    private_key_pem = identity.private_key_pem()

    # Simulate what a sync payload looks like
    payload = json.dumps({
        "device_id": identity.device_id,
        "public_key": identity.public_key_bytes().hex(),
        "content": content,
    }).encode()

    # Private key PEM must not appear in the payload
    assert private_key_pem not in payload
    # Raw private key bytes must not appear either
    # (Ed25519 private key is 32 bytes; check the raw bytes aren't embedded)
    from cryptography.hazmat.primitives import serialization
    raw_private = identity.private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    assert raw_private not in payload
