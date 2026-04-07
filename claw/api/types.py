"""API data models for Anthropic and OpenAI-compatible providers.

Maps to: rust/crates/api/src/types.rs
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Literal


# ---------------------------------------------------------------------------
# Request types
# ---------------------------------------------------------------------------

@dataclass
class MessageRequest:
    model: str
    max_tokens: int
    messages: list[InputMessage]
    system: str | None = None
    tools: list[ToolDefinition] | None = None
    tool_choice: ToolChoice | None = None
    stream: bool = False

    def with_streaming(self) -> MessageRequest:
        self.stream = True
        return self

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "messages": [m.to_dict() for m in self.messages],
        }
        if self.system is not None:
            d["system"] = self.system
        if self.tools is not None:
            d["tools"] = [t.to_dict() for t in self.tools]
        if self.tool_choice is not None:
            d["tool_choice"] = self.tool_choice.to_dict()
        if self.stream:
            d["stream"] = True
        return d


@dataclass
class InputMessage:
    role: str
    content: list[InputContentBlock]

    @classmethod
    def user_text(cls, text: str) -> InputMessage:
        return cls(role="user", content=[TextInputBlock(text=text)])

    @classmethod
    def user_tool_result(
        cls, tool_use_id: str, content: str, is_error: bool = False
    ) -> InputMessage:
        return cls(
            role="user",
            content=[
                ToolResultBlock(
                    tool_use_id=tool_use_id,
                    content=[ToolResultTextContent(text=content)],
                    is_error=is_error,
                )
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": [b.to_dict() for b in self.content],
        }


# ---------------------------------------------------------------------------
# Input content blocks (tagged union via subclasses)
# ---------------------------------------------------------------------------

@dataclass
class InputContentBlock:
    """Base class for input content blocks."""

    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class TextInputBlock(InputContentBlock):
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass
class ToolUseInputBlock(InputContentBlock):
    id: str
    name: str
    input: Any

    def to_dict(self) -> dict[str, Any]:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


@dataclass
class ToolResultBlock(InputContentBlock):
    tool_use_id: str
    content: list[ToolResultContent]
    is_error: bool = False

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": [c.to_dict() for c in self.content],
        }
        if self.is_error:
            d["is_error"] = True
        return d


# ---------------------------------------------------------------------------
# Tool result content blocks
# ---------------------------------------------------------------------------

@dataclass
class ToolResultContent:
    def to_dict(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class ToolResultTextContent(ToolResultContent):
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"type": "text", "text": self.text}


@dataclass
class ToolResultJsonContent(ToolResultContent):
    value: Any

    def to_dict(self) -> dict[str, Any]:
        return {"type": "json", "value": self.value}


# ---------------------------------------------------------------------------
# Tool definitions
# ---------------------------------------------------------------------------

@dataclass
class ToolDefinition:
    name: str
    input_schema: dict[str, Any]
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"name": self.name, "input_schema": self.input_schema}
        if self.description is not None:
            d["description"] = self.description
        return d


# ---------------------------------------------------------------------------
# Tool choice
# ---------------------------------------------------------------------------

@dataclass
class ToolChoice:
    type: Literal["auto", "any", "tool"]
    name: str | None = None

    @classmethod
    def auto(cls) -> ToolChoice:
        return cls(type="auto")

    @classmethod
    def any(cls) -> ToolChoice:
        return cls(type="any")

    @classmethod
    def tool(cls, name: str) -> ToolChoice:
        return cls(type="tool", name=name)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"type": self.type}
        if self.name is not None:
            d["name"] = self.name
        return d


# ---------------------------------------------------------------------------
# Response types
# ---------------------------------------------------------------------------

@dataclass
class MessageResponse:
    id: str
    type: str
    role: str
    content: list[OutputContentBlock]
    model: str
    usage: Usage
    stop_reason: str | None = None
    stop_sequence: str | None = None
    request_id: str | None = None

    def total_tokens(self) -> int:
        return self.usage.total_tokens()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageResponse:
        return cls(
            id=data["id"],
            type=data.get("type", "message"),
            role=data.get("role", "assistant"),
            content=[OutputContentBlock.from_dict(b) for b in data.get("content", [])],
            model=data["model"],
            usage=Usage.from_dict(data["usage"]),
            stop_reason=data.get("stop_reason"),
            stop_sequence=data.get("stop_sequence"),
            request_id=data.get("request_id"),
        )


# ---------------------------------------------------------------------------
# Output content blocks (tagged union via subclasses)
# ---------------------------------------------------------------------------

@dataclass
class OutputContentBlock:
    """Base class for output content blocks."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OutputContentBlock:
        block_type = data.get("type", "")
        if block_type == "text":
            return TextOutputBlock(text=data["text"])
        if block_type == "tool_use":
            return ToolUseOutputBlock(id=data["id"], name=data["name"], input=data["input"])
        if block_type == "thinking":
            return ThinkingBlock(thinking=data.get("thinking", ""), signature=data.get("signature"))
        if block_type == "redacted_thinking":
            return RedactedThinkingBlock(data=data.get("data"))
        return TextOutputBlock(text=str(data))


@dataclass
class TextOutputBlock(OutputContentBlock):
    text: str = ""


@dataclass
class ToolUseOutputBlock(OutputContentBlock):
    id: str = ""
    name: str = ""
    input: Any = None


@dataclass
class ThinkingBlock(OutputContentBlock):
    thinking: str = ""
    signature: str | None = None


@dataclass
class RedactedThinkingBlock(OutputContentBlock):
    data: Any = None


# ---------------------------------------------------------------------------
# Usage / tokens
# ---------------------------------------------------------------------------

@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Usage:
        return cls(
            input_tokens=data.get("input_tokens", 0),
            output_tokens=data.get("output_tokens", 0),
            cache_creation_input_tokens=data.get("cache_creation_input_tokens", 0),
            cache_read_input_tokens=data.get("cache_read_input_tokens", 0),
        )


# ---------------------------------------------------------------------------
# Stream events (tagged union via subclasses)
# ---------------------------------------------------------------------------

@dataclass
class StreamEvent:
    """Base class for SSE stream events."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StreamEvent:
        event_type = data.get("type", "")
        if event_type == "message_start":
            return MessageStartEvent(
                message=MessageResponse.from_dict(data["message"])
            )
        if event_type == "message_delta":
            return MessageDeltaEvent(
                delta=MessageDelta.from_dict(data["delta"]),
                usage=Usage.from_dict(data["usage"]),
            )
        if event_type == "content_block_start":
            return ContentBlockStartEvent(
                index=data["index"],
                content_block=OutputContentBlock.from_dict(data["content_block"]),
            )
        if event_type == "content_block_delta":
            return ContentBlockDeltaEvent(
                index=data["index"],
                delta=ContentBlockDelta.from_dict(data["delta"]),
            )
        if event_type == "content_block_stop":
            return ContentBlockStopEvent(index=data["index"])
        if event_type == "message_stop":
            return MessageStopEvent()
        return StreamEvent()


@dataclass
class MessageStartEvent(StreamEvent):
    message: MessageResponse | None = None


@dataclass
class MessageDelta:
    stop_reason: str | None = None
    stop_sequence: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageDelta:
        return cls(
            stop_reason=data.get("stop_reason"),
            stop_sequence=data.get("stop_sequence"),
        )


@dataclass
class MessageDeltaEvent(StreamEvent):
    delta: MessageDelta = field(default_factory=MessageDelta)
    usage: Usage = field(default_factory=Usage)


@dataclass
class ContentBlockStartEvent(StreamEvent):
    index: int = 0
    content_block: OutputContentBlock | None = None


@dataclass
class ContentBlockDelta:
    """Base for content block deltas."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContentBlockDelta:
        delta_type = data.get("type", "")
        if delta_type == "text_delta":
            return TextDelta(text=data.get("text", ""))
        if delta_type == "input_json_delta":
            return InputJsonDelta(partial_json=data.get("partial_json", ""))
        if delta_type == "thinking_delta":
            return ThinkingDelta(thinking=data.get("thinking", ""))
        if delta_type == "signature_delta":
            return SignatureDelta(signature=data.get("signature", ""))
        return ContentBlockDelta()


@dataclass
class TextDelta(ContentBlockDelta):
    text: str = ""


@dataclass
class InputJsonDelta(ContentBlockDelta):
    partial_json: str = ""


@dataclass
class ThinkingDelta(ContentBlockDelta):
    thinking: str = ""


@dataclass
class SignatureDelta(ContentBlockDelta):
    signature: str = ""


@dataclass
class ContentBlockDeltaEvent(StreamEvent):
    index: int = 0
    delta: ContentBlockDelta = field(default_factory=ContentBlockDelta)


@dataclass
class ContentBlockStopEvent(StreamEvent):
    index: int = 0


@dataclass
class MessageStopEvent(StreamEvent):
    pass
