"""Tests for session compaction."""

from axion.runtime.compact import (
    CompactionConfig,
    compact_session,
    estimate_session_tokens,
)
from axion.runtime.session import Session


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


def test_estimate_counts_tool_results():
    """Tool result output must be counted, not treated as a flat 100 chars (regression)."""
    from axion.runtime.compact import estimate_session_tokens
    from axion.runtime.session import (
        ConversationMessage,
        MessageRole,
        Session,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
    )

    big = "x" * 40_000  # ~10k tokens of tool output
    session = Session()
    session.push_message(ConversationMessage(role=MessageRole.USER, blocks=[TextBlock(text="read the file")]))
    session.push_message(ConversationMessage(
        role=MessageRole.ASSISTANT,
        blocks=[ToolUseBlock(id="t1", name="Read", input='{"file_path": "big.txt"}')],
    ))
    session.push_message(ConversationMessage(
        role=MessageRole.USER,
        blocks=[ToolResultBlock(tool_use_id="t1", tool_name="Read", output=big)],
    ))
    est = estimate_session_tokens(session)
    assert est > 9_000, f"tool output not counted: estimate {est}"


def test_context_window_from_env(monkeypatch):
    from axion.runtime.conversation import _context_window_for
    monkeypatch.delenv("AXION_COMPAT_CONTEXT_WINDOW", raising=False)
    assert _context_window_for("claude-sonnet-4-6") == 200_000
    assert _context_window_for("rex") == 200_000  # unknown -> default
    monkeypatch.setenv("AXION_COMPAT_CONTEXT_WINDOW", "16384")
    assert _context_window_for("rex") == 16384


def test_compaction_never_orphans_tool_result():
    """The split must not leave a tool_result whose tool_use was summarized away (provider 400)."""
    from axion.runtime.compact import CompactionConfig, compact_session
    from axion.runtime.session import (
        ConversationMessage,
        MessageRole,
        Session,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
    )

    s = Session()
    # Enough history to compact, ending with a tool_use/tool_result pair as the recent tail.
    for i in range(8):
        s.push_message(ConversationMessage(role=MessageRole.USER, blocks=[TextBlock(text=f"q{i} " + "x"*3000)]))
        s.push_message(ConversationMessage(role=MessageRole.ASSISTANT, blocks=[ToolUseBlock(id=f"t{i}", name="Read", input="{}")]))
        s.push_message(ConversationMessage(role=MessageRole.USER, blocks=[ToolResultBlock(tool_use_id=f"t{i}", tool_name="Read", output="y"*3000)]))

    compact_session(s, CompactionConfig(max_tokens=1))

    # After compaction, no message may contain a ToolResultBlock whose matching ToolUseBlock is absent.
    seen_tool_use_ids = set()
    for m in s.messages:
        for b in m.blocks:
            if isinstance(b, ToolUseBlock):
                seen_tool_use_ids.add(b.id)
    for m in s.messages:
        for b in m.blocks:
            if isinstance(b, ToolResultBlock):
                assert b.tool_use_id in seen_tool_use_ids, f"orphaned tool_result {b.tool_use_id}"


def test_safe_split_index_backs_off_tool_result():
    from axion.runtime.compact import _safe_split_index
    from axion.runtime.session import ConversationMessage, MessageRole, TextBlock, ToolResultBlock, ToolUseBlock

    msgs = [
        ConversationMessage(role=MessageRole.USER, blocks=[TextBlock(text="a")]),
        ConversationMessage(role=MessageRole.ASSISTANT, blocks=[ToolUseBlock(id="t", name="R", input="{}")]),
        ConversationMessage(role=MessageRole.USER, blocks=[ToolResultBlock(tool_use_id="t", tool_name="R", output="o")]),
        ConversationMessage(role=MessageRole.USER, blocks=[TextBlock(text="b")]),
    ]
    # preserve_recent=2 would cut at idx 2 (a tool_result) -> must back off to 1 (the tool_use msg).
    assert _safe_split_index(msgs, 2) == 1
