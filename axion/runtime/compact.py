"""Session compaction.

Maps to: rust/crates/runtime/src/compact.rs
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from axion.runtime.session import (
    ConversationMessage,
    ImageBlock,
    MessageRole,
    Session,
    SessionCompaction,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)

if TYPE_CHECKING:
    from axion.api.client import ProviderClient

logger = logging.getLogger(__name__)


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


def _safe_split_index(messages: list, preserve_recent: int) -> int:
    """Boundary between summarized-old and kept-recent messages that never orphans a tool_result.

    Starts at total-preserve_recent and moves earlier while the first kept message contains a
    ToolResultBlock, so the assistant tool_use that produced it is kept too (never summarized away).
    """
    idx = len(messages) - preserve_recent
    while idx > 0 and any(isinstance(b, ToolResultBlock) for b in messages[idx].blocks):
        idx -= 1
    return idx


def estimate_session_tokens(session: Session) -> int:
    """Rough estimate of token count in a session (~4 chars per token).

    Tool results and tool-use inputs carry the real bulk of an agent session (a single file
    read can be thousands of tokens), so they must be counted by their actual length. Counting
    them as a flat 100 chars — as this did previously — made the estimate wildly low, which in
    turn silently disabled auto-compaction and let the prompt overflow the model's context window.
    """
    total_chars = 0
    for msg in session.messages:
        for block in msg.blocks:
            if isinstance(block, TextBlock):
                total_chars += len(block.text)
            elif isinstance(block, ToolResultBlock):
                total_chars += len(block.output) + len(block.tool_name)
            elif isinstance(block, ToolUseBlock):
                total_chars += len(block.input) + len(block.name)
            elif isinstance(block, ImageBlock):
                total_chars += 1000  # images cost roughly this many tokens once tiled
            else:
                total_chars += 100
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

    # Split into old and recent, snapping the boundary so it never falls between an assistant
    # tool_use and its tool_result(s). Cutting there would summarize away the tool_use while keeping
    # an orphaned tool_result as the first recent message, which the provider rejects (400) and kills
    # the very next request. Move the boundary earlier until recent no longer starts with a result.
    split_idx = _safe_split_index(session.messages, cfg.preserve_recent_messages)
    if split_idx <= 0:
        return None
    old_messages = session.messages[:split_idx]
    recent_messages = session.messages[split_idx:]

    # Build summary from old messages. Include tool activity, not just text: tool calls and their
    # results are the bulk of an agent session (files read, commands run), so a text-only summary
    # threw away exactly the context the model needs to keep working. Keep names + truncated output.
    summary_parts: list[str] = []
    for msg in old_messages:
        for block in msg.blocks:
            if isinstance(block, TextBlock):
                text = block.text[:200] + "..." if len(block.text) > 200 else block.text
                summary_parts.append(f"[{msg.role.value}] {text}")
            elif isinstance(block, ToolUseBlock):
                args = block.input if len(block.input) <= 120 else block.input[:120] + "..."
                summary_parts.append(f"[tool call] {block.name}({args})")
            elif isinstance(block, ToolResultBlock):
                out = block.output.strip()
                out = out[:200] + "..." if len(out) > 200 else out
                summary_parts.append(f"[tool result: {block.tool_name}] {out}")

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


# ---------------------------------------------------------------------------
# Model-based intelligent compaction
# ---------------------------------------------------------------------------


async def model_compact_session(
    session: Session,
    provider: "ProviderClient",
    model: str,
    config: CompactionConfig | None = None,
) -> CompactionResult | None:
    """Use a model to produce an intelligent summary for compaction.

    1. Builds a summary request asking the model to summarize old messages.
    2. Sends it to the API.
    3. Replaces old messages with the model-generated summary.

    Falls back to the heuristic ``compact_session`` if the API call fails.
    """
    from axion.api.client import max_tokens_for_model, resolve_model_alias
    from axion.api.types import InputMessage, MessageRequest, TextInputBlock

    cfg = config or CompactionConfig()

    estimated_tokens = estimate_session_tokens(session)
    if estimated_tokens < cfg.max_tokens:
        return None

    total_messages = len(session.messages)
    if total_messages <= cfg.preserve_recent_messages:
        return None

    # Same tool_use/tool_result boundary guard as the heuristic path (see _safe_split_index).
    split_idx = _safe_split_index(session.messages, cfg.preserve_recent_messages)
    if split_idx <= 0:
        return None
    old_messages = session.messages[:split_idx]
    recent_messages = session.messages[split_idx:]

    # Build text representation of old messages for the summariser
    old_text_parts: list[str] = []
    for msg in old_messages:
        for block in msg.blocks:
            if isinstance(block, TextBlock):
                text = block.text[:500] if len(block.text) > 500 else block.text
                old_text_parts.append(f"[{msg.role.value}] {text}")

    old_text = "\n".join(old_text_parts)

    # Build a summarisation request
    summary_prompt = (
        "Summarise the following conversation history concisely. "
        "Preserve key decisions, tool outputs, file paths, and any context "
        "the assistant will need to continue the conversation.\n\n"
        f"{old_text}"
    )

    resolved_model = resolve_model_alias(model)
    request = MessageRequest(
        model=resolved_model,
        max_tokens=min(cfg.summary_max_tokens, max_tokens_for_model(resolved_model)),
        messages=[
            InputMessage(
                role="user",
                content=[TextInputBlock(text=summary_prompt)],
            )
        ],
        system="You are a conversation summariser. Produce a concise summary.",
        stream=False,
    )

    try:
        response = await provider.send_message(request)
        # Extract text from the response
        summary_text = ""
        if response.content:
            for block in response.content:
                if hasattr(block, "text"):
                    summary_text += block.text
        if not summary_text:
            raise ValueError("Empty summary from model")
    except Exception as exc:
        logger.warning(
            "Model-based compaction failed, falling back to heuristic: %s", exc
        )
        return compact_session(session, cfg)

    # Replace old messages with model-generated summary
    summary_message = ConversationMessage(
        role=MessageRole.USER,
        blocks=[
            TextBlock(
                text=f"[Session compacted by model. Summary of {split_idx} earlier messages:]\n{summary_text}"
            )
        ],
    )

    session.messages = [summary_message] + recent_messages

    compaction_count = (session.compaction.count + 1) if session.compaction else 1
    session.compaction = SessionCompaction(
        count=compaction_count,
        removed_message_count=split_idx,
        summary=summary_text[:500],
    )

    tokens_after = estimate_session_tokens(session)

    return CompactionResult(
        removed_count=split_idx,
        summary=summary_text[:200],
        estimated_tokens_before=estimated_tokens,
        estimated_tokens_after=tokens_after,
    )
