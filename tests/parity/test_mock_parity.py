"""End-to-end integration tests using the mock Anthropic server.

These tests validate the full request/response cycle:
  Client -> Mock Server -> SSE parsing -> Stream events -> Response assembly
"""

from __future__ import annotations

import pytest

from axion.api.anthropic import AnthropicClient, AuthCredentials
from axion.api.types import (
    ContentBlockDeltaEvent,
    InputMessage,
    MessageRequest,
    MessageResponse,
    MessageStartEvent,
    MessageStopEvent,
    StreamEvent,
    TextDelta,
    TextOutputBlock,
)
from tests.mock_anthropic.server import MockAnthropicService


@pytest.fixture
async def mock_service():
    """Start a mock Anthropic server for the test."""
    service = await MockAnthropicService.spawn()
    yield service
    await service.shutdown()


def _make_client(base_url: str) -> AnthropicClient:
    """Create an AnthropicClient pointing at the mock server."""
    return AnthropicClient(
        auth=AuthCredentials.from_api_key("fake-test-key"),
        base_url=base_url,
    )


def _make_request(text: str, stream: bool = False) -> MessageRequest:
    return MessageRequest(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[InputMessage.user_text(text)],
        stream=stream,
    )


# ---------------------------------------------------------------------------
# Non-streaming tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_simple_text_response(mock_service):
    """Send a basic message and get a text response."""
    client = _make_client(mock_service.base_url)
    try:
        request = _make_request("Hello")
        response = await client.send_message(request)

        assert isinstance(response, MessageResponse)
        assert response.id.startswith("msg_")
        assert response.role == "assistant"
        assert len(response.content) >= 1
        assert isinstance(response.content[0], TextOutputBlock)
        assert response.content[0].text  # Non-empty text
        assert response.usage.input_tokens > 0
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_request_captured(mock_service):
    """Verify the mock server captures request metadata."""
    client = _make_client(mock_service.base_url)
    try:
        await client.send_message(_make_request("Test capture"))

        captured = mock_service.captured_requests
        assert len(captured) == 1
        assert captured[0].method == "POST"
        assert captured[0].path == "/v1/messages"
        assert "x-api-key" in captured[0].headers or "authorization" in captured[0].headers
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Streaming tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_text(mock_service):
    """Stream a text response and collect all events."""
    client = _make_client(mock_service.base_url)
    try:
        request = _make_request("PARITY_SCENARIO:streaming_text Hello", stream=True)
        events: list[StreamEvent] = []

        async for event in client.stream_message(request):
            events.append(event)

        # Should have: message_start, content_block_start, deltas, block_stop, message_delta, message_stop
        assert len(events) >= 4

        # First event should be message_start
        assert isinstance(events[0], MessageStartEvent)

        # Should contain text deltas
        text_deltas = [e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)]
        assert len(text_deltas) >= 1

        # Assemble full text
        full_text = "".join(d.delta.text for d in text_deltas)
        assert len(full_text) > 0

        # Last event should be message_stop
        assert isinstance(events[-1], MessageStopEvent)
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_scenario_read_file_roundtrip(mock_service):
    """Test the read file tool use scenario."""
    client = _make_client(mock_service.base_url)
    try:
        # First request: model should request a Read tool
        request = _make_request("PARITY_SCENARIO:read_file_roundtrip Read /tmp/test.txt")
        response = await client.send_message(request)

        assert response.stop_reason == "tool_use"
        # Should have a tool_use content block
        tool_uses = [b for b in response.content if hasattr(b, "name")]
        assert len(tool_uses) >= 1
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_scenario_token_cost_reporting(mock_service):
    """Test token cost reporting scenario."""
    client = _make_client(mock_service.base_url)
    try:
        request = _make_request("PARITY_SCENARIO:token_cost_reporting Report costs")
        response = await client.send_message(request)

        assert response.usage.input_tokens > 0
        assert response.content  # Should have text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_multiple_requests_captured(mock_service):
    """Multiple requests should all be captured."""
    client = _make_client(mock_service.base_url)
    try:
        await client.send_message(_make_request("First"))
        await client.send_message(_make_request("Second"))
        await client.send_message(_make_request("Third"))

        assert len(mock_service.captured_requests) == 3
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# Error handling tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_streaming_assembles_text(mock_service):
    """Verify that chunked SSE text deltas are assembled correctly."""
    client = _make_client(mock_service.base_url)
    try:
        request = _make_request("PARITY_SCENARIO:streaming_text Chunked test", stream=True)

        text_parts: list[str] = []
        async for event in client.stream_message(request):
            if isinstance(event, ContentBlockDeltaEvent) and isinstance(event.delta, TextDelta):
                text_parts.append(event.delta.text)

        full_text = "".join(text_parts)
        assert len(full_text) > 0
        # The mock splits "Hello! How can I help you today?" into two chunks
        assert "Hello" in full_text or "help" in full_text
    finally:
        await client.close()
