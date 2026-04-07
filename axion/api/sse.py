"""Server-Sent Events (SSE) parser.

Maps to: rust/crates/api/src/sse.rs
"""

from __future__ import annotations

import json

from axion.api.error import InvalidSseFrameError
from axion.api.types import StreamEvent


class SseParser:
    """Incremental SSE frame parser that handles chunked delivery."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def push(self, chunk: bytes) -> list[StreamEvent]:
        """Push a chunk of data and return any complete events."""
        self._buffer.extend(chunk)
        events: list[StreamEvent] = []

        while True:
            frame = self._next_frame()
            if frame is None:
                break
            event = parse_frame(frame)
            if event is not None:
                events.append(event)

        return events

    def finish(self) -> list[StreamEvent]:
        """Flush any remaining data in the buffer."""
        if not self._buffer:
            return []

        trailing = self._buffer.decode("utf-8", errors="replace")
        self._buffer.clear()

        event = parse_frame(trailing)
        return [event] if event is not None else []

    def _next_frame(self) -> str | None:
        """Extract the next complete frame from the buffer."""
        # Look for \n\n separator
        pos = self._buffer.find(b"\n\n")
        sep_len = 2

        if pos == -1:
            # Try \r\n\r\n
            pos = self._buffer.find(b"\r\n\r\n")
            sep_len = 4

        if pos == -1:
            return None

        frame_bytes = bytes(self._buffer[: pos])
        del self._buffer[: pos + sep_len]
        return frame_bytes.decode("utf-8", errors="replace")


def parse_frame(frame: str) -> StreamEvent | None:
    """Parse a single SSE frame into a StreamEvent."""
    trimmed = frame.strip()
    if not trimmed:
        return None

    data_lines: list[str] = []
    event_name: str | None = None

    for line in trimmed.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[len("event:"):].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())

    if event_name == "ping":
        return None

    if not data_lines:
        return None

    payload = "\n".join(data_lines)
    if payload == "[DONE]":
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InvalidSseFrameError(f"Invalid JSON in SSE data: {exc}") from exc

    return StreamEvent.from_dict(data)
