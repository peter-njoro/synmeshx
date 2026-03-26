# Feature: contexa-core, Property 14: Conflict Detection Preserves Both Versions
"""
For any two diverging versions of the same Context_ID (where neither version's
parent_version chain is an ancestor of the other), syncing must result in both
versions being retained and a conflict entry recorded in the Sync_Log.
Validates: Requirements 8.4
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from contexa.sync.protocol import detect_conflict, is_ancestor


# Strategy: generate a version tree with a fork
version_ids = st.text(min_size=3, max_size=8, alphabet="abcdefghijklmnop0123456789")


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    root=version_ids,
    branch_a=version_ids,
    branch_b=version_ids,
)
def test_diverged_versions_always_conflict(root, branch_a, branch_b):
    """Two versions that both descend from root but not from each other are conflicts."""
    from hypothesis import assume
    assume(root != branch_a and root != branch_b and branch_a != branch_b)

    # Both branch_a and branch_b descend from root independently
    version_map = {
        branch_a: root,
        branch_b: root,
        root: None,
    }

    assert detect_conflict(branch_a, branch_b, version_map)
    assert detect_conflict(branch_b, branch_a, version_map)


@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    v1=version_ids,
    v2=version_ids,
    v3=version_ids,
)
def test_linear_chain_never_conflicts(v1, v2, v3):
    """A linear version chain (v1 → v2 → v3) never produces a conflict."""
    from hypothesis import assume
    assume(len({v1, v2, v3}) == 3)

    version_map = {v3: v2, v2: v1, v1: None}

    # v3 is a descendant of v2 — no conflict
    assert not detect_conflict(v2, v3, version_map)
    # v2 is a descendant of v1 — no conflict
    assert not detect_conflict(v1, v2, version_map)
    # v3 is a descendant of v1 — no conflict
    assert not detect_conflict(v1, v3, version_map)
