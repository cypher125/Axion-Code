"""Tests for API types."""

from axion.api.types import (
    ContentBlockDeltaEvent,
    InputMessage,
    MessageRequest,
    MessageResponse,
    StreamEvent,
    TextDelta,
    TextOutputBlock,
    ToolChoice,
    Usage,
)


def test_message_request_to_dict():
    req = MessageRequest(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[InputMessage.user_text("Hello")],
    )
    d = req.to_dict()
    assert d["model"] == "claude-sonnet-4-6"
    assert d["max_tokens"] == 1024
    assert len(d["messages"]) == 1
    assert "stream" not in d  # False should not be serialized


def test_message_request_streaming():
    req = MessageRequest(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[InputMessage.user_text("Hello")],
    ).with_streaming()
    d = req.to_dict()
    assert d["stream"] is True


def test_usage_total_tokens():
    usage = Usage(
        input_tokens=10,
        output_tokens=4,
        cache_creation_input_tokens=2,
        cache_read_input_tokens=3,
    )
    assert usage.total_tokens() == 19


def test_message_response_from_dict():
    data = {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "Hello!"}],
        "model": "claude-sonnet-4-6",
        "usage": {"input_tokens": 10, "output_tokens": 5},
        "stop_reason": "end_turn",
    }
    response = MessageResponse.from_dict(data)
    assert response.id == "msg_123"
    assert len(response.content) == 1
    assert isinstance(response.content[0], TextOutputBlock)
    assert response.content[0].text == "Hello!"
    assert response.total_tokens() == 15


def test_stream_event_from_dict():
    data = {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "text_delta", "text": "Hello"},
    }
    event = StreamEvent.from_dict(data)
    assert isinstance(event, ContentBlockDeltaEvent)
    assert isinstance(event.delta, TextDelta)
    assert event.delta.text == "Hello"


def test_tool_choice():
    auto = ToolChoice.auto()
    assert auto.to_dict() == {"type": "auto"}

    tool = ToolChoice.tool("Read")
    assert tool.to_dict() == {"type": "tool", "name": "Read"}


def test_input_message_user_tool_result():
    msg = InputMessage.user_tool_result("tu_1", "file contents", is_error=False)
    assert msg.role == "user"
    d = msg.to_dict()
    assert d["content"][0]["type"] == "tool_result"
    assert d["content"][0]["tool_use_id"] == "tu_1"
