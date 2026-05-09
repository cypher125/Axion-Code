"""Session persistence with JSONL format.

Maps to: rust/crates/runtime/src/session.rs
"""

from __future__ import annotations

import enum
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from axion.runtime.usage import TokenUsage

SESSION_VERSION = 1
ROTATE_AFTER_BYTES = 256 * 1024  # 256 KB
MAX_ROTATED_FILES = 3


class MessageRole(enum.Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


# ---------------------------------------------------------------------------
# Content blocks (tagged union via subclasses)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ContentBlock:
    """Base class for session content blocks."""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class TextBlock(ContentBlock):
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass(frozen=True)
class ToolUseBlock(ContentBlock):
    id: str
    name: str
    input: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


@dataclass(frozen=True)
class ImageBlock(ContentBlock):
    """Image content block — stores base64 data for session persistence."""
    media_type: str  # e.g. "image/png", "image/jpeg"
    data: str  # base64-encoded

    def to_dict(self) -> dict[str, Any]:
        return {"type": "image", "media_type": self.media_type, "data": self.data}


@dataclass(frozen=True)
class ToolResultBlock(ContentBlock):
    tool_use_id: str
    tool_name: str
    output: str
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "tool_name": self.tool_name,
            "output": self.output,
            "is_error": self.is_error,
        }


def content_block_from_dict(data: dict[str, Any]) -> ContentBlock:
    """Deserialize a content block from a dict."""
    block_type = data.get("type", "text")
    if block_type == "text":
        return TextBlock(text=data.get("text", ""))
    if block_type == "tool_use":
        return ToolUseBlock(id=data["id"], name=data["name"], input=data.get("input", ""))
    if block_type == "image":
        return ImageBlock(
            media_type=data.get("media_type", "image/png"),
            data=data.get("data", ""),
        )
    if block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=data["tool_use_id"],
            tool_name=data.get("tool_name", ""),
            output=data.get("output", ""),
            is_error=data.get("is_error", False),
        )
    return TextBlock(text=str(data))


# ---------------------------------------------------------------------------
# Conversation message
# ---------------------------------------------------------------------------

@dataclass
class ConversationMessage:
    role: MessageRole
    blocks: list[ContentBlock]
    usage: TokenUsage | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "role": self.role.value,
            "blocks": [b.to_dict() for b in self.blocks],
        }
        if self.usage is not None:
            d["usage"] = {
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "cache_creation_input_tokens": self.usage.cache_creation_input_tokens,
                "cache_read_input_tokens": self.usage.cache_read_input_tokens,
            }
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationMessage:
        role = MessageRole(data["role"])
        blocks = [content_block_from_dict(b) for b in data.get("blocks", [])]
        usage_data = data.get("usage")
        usage = None
        if usage_data:
            usage = TokenUsage(
                input_tokens=usage_data.get("input_tokens", 0),
                output_tokens=usage_data.get("output_tokens", 0),
                cache_creation_input_tokens=usage_data.get("cache_creation_input_tokens", 0),
                cache_read_input_tokens=usage_data.get("cache_read_input_tokens", 0),
            )
        return cls(role=role, blocks=blocks, usage=usage)


# ---------------------------------------------------------------------------
# Session compaction and fork metadata
# ---------------------------------------------------------------------------

@dataclass
class SessionCompaction:
    count: int
    removed_message_count: int
    summary: str


@dataclass
class SessionFork:
    parent_session_id: str
    branch_name: str | None = None


# ---------------------------------------------------------------------------
# Session errors
# ---------------------------------------------------------------------------

class SessionError(Exception):
    """Base error for session operations."""


class SessionIoError(SessionError):
    pass


class SessionFormatError(SessionError):
    pass


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _generate_session_id() -> str:
    return uuid.uuid4().hex[:16]


def _current_time_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class Session:
    """Persisted conversational state.

    Maps to: rust/crates/runtime/src/session.rs::Session
    """

    version: int = SESSION_VERSION
    session_id: str = field(default_factory=_generate_session_id)
    created_at_ms: int = field(default_factory=_current_time_ms)
    updated_at_ms: int = field(default_factory=_current_time_ms)
    messages: list[ConversationMessage] = field(default_factory=list)
    compaction: SessionCompaction | None = None
    fork: SessionFork | None = None
    _persistence_path: Path | None = field(default=None, repr=False)

    def with_persistence_path(self, path: Path) -> Session:
        self._persistence_path = path
        return self

    def push_message(self, msg: ConversationMessage) -> None:
        """Append a message and update the timestamp."""
        self.messages.append(msg)
        self.updated_at_ms = _current_time_ms()

    def push_user_text(self, text: str) -> None:
        """Shorthand: append a user text message."""
        self.push_message(
            ConversationMessage(
                role=MessageRole.USER,
                blocks=[TextBlock(text=text)],
            )
        )

    def push_user_image(
        self, media_type: str, data: str, text: str = ""
    ) -> None:
        """Append a user message with an image (and optional text)."""
        blocks: list[ContentBlock] = [ImageBlock(media_type=media_type, data=data)]
        if text:
            blocks.append(TextBlock(text=text))
        self.push_message(
            ConversationMessage(role=MessageRole.USER, blocks=blocks)
        )

    def push_assistant_text(self, text: str, usage: TokenUsage | None = None) -> None:
        """Shorthand: append an assistant text message."""
        self.push_message(
            ConversationMessage(
                role=MessageRole.ASSISTANT,
                blocks=[TextBlock(text=text)],
                usage=usage,
            )
        )

    def message_count(self) -> int:
        return len(self.messages)

    # -----------------------------------------------------------------------
    # Persistence (JSONL)
    # -----------------------------------------------------------------------

    def save(self, path: Path | None = None) -> None:
        """Save session to JSONL file with rotation."""
        target = path or self._persistence_path
        if target is None:
            raise SessionError("No persistence path configured")

        target.parent.mkdir(parents=True, exist_ok=True)

        # Rotate if file is too large
        if target.exists() and target.stat().st_size > ROTATE_AFTER_BYTES:
            self._rotate(target)

        data = self._to_dict()
        line = json.dumps(data, separators=(",", ":"))

        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    @classmethod
    def load(cls, path: Path) -> Session:
        """Load session from JSONL file (reads last complete entry)."""
        if not path.exists():
            raise SessionIoError(f"Session file not found: {path}")

        last_entry: dict[str, Any] | None = None
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        last_entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

        if last_entry is None:
            raise SessionFormatError(f"No valid entries in session file: {path}")

        return cls._from_dict(last_entry, path)

    def _to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "version": self.version,
            "session_id": self.session_id,
            "created_at_ms": self.created_at_ms,
            "updated_at_ms": self.updated_at_ms,
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.compaction:
            d["compaction"] = {
                "count": self.compaction.count,
                "removed_message_count": self.compaction.removed_message_count,
                "summary": self.compaction.summary,
            }
        if self.fork:
            d["fork"] = {
                "parent_session_id": self.fork.parent_session_id,
                "branch_name": self.fork.branch_name,
            }
        return d

    @classmethod
    def _from_dict(cls, data: dict[str, Any], path: Path | None = None) -> Session:
        messages = [ConversationMessage.from_dict(m) for m in data.get("messages", [])]

        compaction = None
        if "compaction" in data and data["compaction"]:
            c = data["compaction"]
            compaction = SessionCompaction(
                count=c["count"],
                removed_message_count=c["removed_message_count"],
                summary=c["summary"],
            )

        fork = None
        if "fork" in data and data["fork"]:
            f = data["fork"]
            fork = SessionFork(
                parent_session_id=f["parent_session_id"],
                branch_name=f.get("branch_name"),
            )

        session = cls(
            version=data.get("version", SESSION_VERSION),
            session_id=data.get("session_id", _generate_session_id()),
            created_at_ms=data.get("created_at_ms", _current_time_ms()),
            updated_at_ms=data.get("updated_at_ms", _current_time_ms()),
            messages=messages,
            compaction=compaction,
            fork=fork,
        )
        if path:
            session._persistence_path = path
        return session

    @staticmethod
    def _rotate(path: Path) -> None:
        """Rotate session files, keeping up to MAX_ROTATED_FILES."""
        for i in range(MAX_ROTATED_FILES - 1, 0, -1):
            src = path.with_suffix(f".{i}.jsonl")
            dst = path.with_suffix(f".{i + 1}.jsonl")
            if src.exists():
                if i + 1 > MAX_ROTATED_FILES:
                    src.unlink()
                else:
                    src.rename(dst)

        # Rotate current to .1
        rotated = path.with_suffix(".1.jsonl")
        if path.exists():
            path.rename(rotated)
