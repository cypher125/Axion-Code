"""Tests for SSE parser."""

from claw.api.sse import SseParser, parse_frame
from claw.api.types import (
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    TextDelta,
    TextOutputBlock,
)


def test_parse_single_frame():
    frame = (
        "event: content_block_start\n"
        'data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":"Hi"}}'
    )
    event = parse_frame(frame)
    assert event is not None
    assert isinstance(event, ContentBlockStartEvent)
    assert isinstance(event.content_block, TextOutputBlock)
    assert event.content_block.text == "Hi"


def test_parse_empty_frame():
    assert parse_frame("") is None
    assert parse_frame("   ") is None


def test_parse_comment_only():
    assert parse_frame(": this is a comment") is None


def test_parse_ping():
    assert parse_frame("event: ping\ndata: {}") is None


def test_parse_done():
    assert parse_frame("data: [DONE]") is None


def test_chunked_stream():
    parser = SseParser()

    chunk1 = b'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"Hel'
    chunk2 = b'lo"}}\n\n'

    events1 = parser.push(chunk1)
    assert len(events1) == 0  # Not complete yet

    events2 = parser.push(chunk2)
    assert len(events2) == 1
    assert isinstance(events2[0], ContentBlockDeltaEvent)
    assert isinstance(events2[0].delta, TextDelta)
    assert events2[0].delta.text == "Hello"


def test_multiple_events_in_one_push():
    parser = SseParser()
    data = (
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"A"}}\n\n'
        'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"B"}}\n\n'
    )
    events = parser.push(data.encode())
    assert len(events) == 2


def test_finish_flushes():
    parser = SseParser()
    parser.push(b'data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"X"}}')
    events = parser.finish()
    assert len(events) == 1
