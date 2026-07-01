"""
Fixtures specific to unit tests.
"""

import pytest

from contexa.sync.crypto import generate_device_identity


@pytest.fixture
def identity():
    """A fresh device identity (Ed25519 key pair + device_id)."""
    return generate_device_identity()
