# Feature: contexa-core, Property 17: End-to-End Encryption of Relay Payloads
"""
For any sync payload transmitted through the Relay, the bytes received by
the Relay server must not be decryptable to the original plaintext without
the recipient device's X25519 private key.
Validates: Requirements 9.2, 9.3
"""

from __future__ import annotations

import json
import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from cryptography.exceptions import InvalidTag

from contexa.sync.crypto import (
    generate_x25519_keypair,
    derive_session_key,
    encrypt,
    decrypt,
    generate_nonce,
)


json_dicts = st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.one_of(st.integers(min_value=-100, max_value=100), st.text(max_size=20)),
    min_size=1,
    max_size=5,
)


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_relay_cannot_decrypt_payload(content):
    """The relay receives ciphertext it cannot decrypt without the recipient's key."""
    # Device A (sender) and Device B (recipient) key pairs
    priv_a, pub_a = generate_x25519_keypair()
    priv_b, pub_b = generate_x25519_keypair()

    # Relay has a different key pair (simulating relay trying to decrypt)
    priv_relay, pub_relay = generate_x25519_keypair()

    nonce = generate_nonce()
    plaintext = json.dumps(content).encode()
    aad = b"device-a"

    # A derives session key using B's public key
    session_key_ab = derive_session_key(priv_a, pub_b, nonce, "device-a")
    ciphertext = encrypt(session_key_ab, nonce, plaintext, aad)

    # Relay tries to decrypt using its own key — must fail
    relay_key = derive_session_key(priv_relay, pub_a, nonce, "device-a")
    with pytest.raises(Exception):  # InvalidTag
        decrypt(relay_key, nonce, ciphertext, aad)

    # Only B can decrypt correctly
    session_key_ba = derive_session_key(priv_b, pub_a, nonce, "device-a")
    recovered = decrypt(session_key_ba, nonce, ciphertext, aad)
    assert recovered == plaintext


@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(content=json_dicts)
def test_wrong_recipient_cannot_decrypt(content):
    """A device that is not the intended recipient cannot decrypt the payload."""
    priv_a, pub_a = generate_x25519_keypair()
    priv_b, pub_b = generate_x25519_keypair()
    priv_c, pub_c = generate_x25519_keypair()  # unintended recipient

    nonce = generate_nonce()
    plaintext = json.dumps(content).encode()
    aad = b"device-a"

    # A encrypts for B
    key_for_b = derive_session_key(priv_a, pub_b, nonce, "device-a")
    ciphertext = encrypt(key_for_b, nonce, plaintext, aad)

    # C tries to decrypt — must fail
    key_c = derive_session_key(priv_c, pub_a, nonce, "device-a")
    with pytest.raises(Exception):
        decrypt(key_c, nonce, ciphertext, aad)
