"""Tests for session compaction."""

from claw.runtime.compact import (
    CompactionConfig,
    compact_session,
    estimate_session_tokens,
)
from claw.runtime.session import Session


def test_estimate_tokens_empty():
    session = Session()
    assert estimate_session_tokens(session) == 0


def test_estimate_tokens():
    session = Session()
    # Each char ~= 0.25 tokens, so 400 chars ~= 100 tokens
    session.push_user_text("x" * 400)
    tokens = estimate_session_tokens(session)
    assert tokens == 100


def test_compact_below_threshold():
    session = Session()
    session.push_user_text("Hello")
    result = compact_session(session)
    assert result is None  # Below threshold, no compaction needed


def test_compact_above_threshold():
    session = Session()
    # Add many messages to exceed threshold
    for i in range(20):
        session.push_user_text("x" * 50000)  # ~12500 tokens each

    config = CompactionConfig(max_tokens=10_000, preserve_recent_messages=2)
    result = compact_session(session, config)
    assert result is not None
    assert result.removed_count == 18  # 20 - 2 preserved
    assert len(session.messages) == 3  # 1 summary + 2 preserved
    assert session.compaction is not None
    assert session.compaction.count == 1
