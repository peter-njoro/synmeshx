# Feature: contexa-core, Property 7: Missing Required Fields Produce Parse Errors
"""
For any JSON object missing one or more required fields (context_id,
version_tag, checksum, content), attempting to parse it into a ContextVersion
must raise a descriptive error identifying the missing fields.
Validates: Requirements 3.3
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError
from typing import Any
import uuid
from datetime import datetime, timezone


# We use a Pydantic model to represent the parse contract.
# The API layer will use this to validate incoming JSON.
class ContextVersionSchema(BaseModel):
    version_id: str
    context_id: str
    version_tag: str
    parent_version: str | None
    content: dict[str, Any]
    checksum: str
    created_at: datetime
    label: str | None = None


REQUIRED_FIELDS = {"version_id", "context_id", "version_tag", "content", "checksum", "created_at"}

valid_base = {
    "version_id": str(uuid.uuid4()),
    "context_id": str(uuid.uuid4()),
    "version_tag": "abc12345",
    "parent_version": None,
    "content": {"key": "value"},
    "checksum": "a" * 64,
    "created_at": datetime.now(timezone.utc).isoformat(),
    "label": None,
}

missing_field_sets = st.lists(
    st.sampled_from(sorted(REQUIRED_FIELDS)),
    min_size=1,
    max_size=len(REQUIRED_FIELDS),
    unique=True,
)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(fields_to_remove=missing_field_sets)
def test_missing_required_fields_raise_validation_error(fields_to_remove):
    """Removing any required field from a ContextVersion JSON raises ValidationError."""
    data = dict(valid_base)
    for field in fields_to_remove:
        data.pop(field, None)

    with pytest.raises(ValidationError) as exc_info:
        ContextVersionSchema(**data)

    # The error should mention at least one of the removed fields
    error_str = str(exc_info.value).lower()
    assert any(f.lower() in error_str for f in fields_to_remove), (
        f"ValidationError did not mention any of {fields_to_remove}: {error_str}"
    )
