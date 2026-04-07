"""Session compaction.

Maps to: rust/crates/runtime/src/compact.rs
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claw.runtime.session import (
    ConversationMessage,
    MessageRole,
    Session,
    SessionCompaction,
    TextBlock,
)


@dataclass
class CompactionConfig:
    """Configuration for session compaction."""

    max_tokens: int = 100_000
    preserve_recent_messages: int = 4
    summary_max_tokens: int = 2000


@dataclass
class CompactionResult:
    """Result of a compaction operation."""

    removed_count: int
    summary: str
    estimated_tokens_before: int
    estimated_tokens_after: int


def estimate_session_tokens(session: Session) -> int:
    """Rough estimate of token count in a session.

    Uses ~4 chars per token heuristic.
    """
    total_chars = 0
    for msg in session.messages:
        for block in msg.blocks:
            if isinstance(block, TextBlock):
                total_chars += len(block.text)
            else:
                total_chars += 100  # Rough estimate for non-text blocks
    return total_chars // 4


def compact_session(
    session: Session,
    config: CompactionConfig | None = None,
) -> CompactionResult | None:
    """Compact a session by summarizing old messages.

    Preserves the most recent messages and replaces older ones
    with a summary message.
    """
    cfg = config or CompactionConfig()

    estimated_tokens = estimate_session_tokens(session)
    if estimated_tokens < cfg.max_tokens:
        return None

    total_messages = len(session.messages)
    if total_messages <= cfg.preserve_recent_messages:
        return None

    # Split into old and recent
    split_idx = total_messages - cfg.preserve_recent_messages
    old_messages = session.messages[:split_idx]
    recent_messages = session.messages[split_idx:]

    # Build summary from old messages
    summary_parts: list[str] = []
    for msg in old_messages:
        for block in msg.blocks:
            if isinstance(block, TextBlock):
                # Truncate long texts
                text = block.text[:200] + "..." if len(block.text) > 200 else block.text
                summary_parts.append(f"[{msg.role.value}] {text}")

    summary = "\n".join(summary_parts)
    if len(summary) > cfg.summary_max_tokens * 4:
        summary = summary[: cfg.summary_max_tokens * 4] + "\n... (summary truncated)"

    # Replace old messages with summary
    summary_message = ConversationMessage(
        role=MessageRole.USER,
        blocks=[TextBlock(text=f"[Session compacted. Summary of {split_idx} earlier messages:]\n{summary}")],
    )

    session.messages = [summary_message] + recent_messages

    # Update compaction metadata
    compaction_count = (session.compaction.count + 1) if session.compaction else 1
    session.compaction = SessionCompaction(
        count=compaction_count,
        removed_message_count=split_idx,
        summary=summary[:500],
    )

    tokens_after = estimate_session_tokens(session)

    return CompactionResult(
        removed_count=split_idx,
        summary=summary[:200],
        estimated_tokens_before=estimated_tokens,
        estimated_tokens_after=tokens_after,
    )
