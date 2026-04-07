"""Mock Anthropic API scenarios for parity testing.

Maps to: rust/crates/mock-anthropic-service/src/lib.rs (Scenario enum)
"""

from __future__ import annotations

import enum
import json
from dataclasses import dataclass
from typing import Any


class Scenario(enum.Enum):
    """Test scenarios matching the Rust mock service."""

    STREAMING_TEXT = "streaming_text"
    READ_FILE_ROUNDTRIP = "read_file_roundtrip"
    GREP_CHUNK_ASSEMBLY = "grep_chunk_assembly"
    WRITE_FILE_ALLOWED = "write_file_allowed"
    WRITE_FILE_DENIED = "write_file_denied"
    MULTI_TOOL_TURN_ROUNDTRIP = "multi_tool_turn_roundtrip"
    BASH_STDOUT_ROUNDTRIP = "bash_stdout_roundtrip"
    BASH_PERMISSION_PROMPT_APPROVED = "bash_permission_prompt_approved"
    BASH_PERMISSION_PROMPT_DENIED = "bash_permission_prompt_denied"
    PLUGIN_TOOL_ROUNDTRIP = "plugin_tool_roundtrip"
    AUTO_COMPACT_TRIGGERED = "auto_compact_triggered"
    TOKEN_COST_REPORTING = "token_cost_reporting"

    @classmethod
    def from_name(cls, name: str) -> Scenario | None:
        for s in cls:
            if s.value == name:
                return s
        return None


def detect_scenario(messages: list[dict[str, Any]]) -> Scenario | None:
    """Detect scenario from PARITY_SCENARIO: prefix in message text."""
    for msg in messages:
        for block in msg.get("content", []):
            text = ""
            if isinstance(block, str):
                text = block
            elif isinstance(block, dict):
                text = block.get("text", "")
            if "PARITY_SCENARIO:" in text:
                name = text.split("PARITY_SCENARIO:")[1].strip().split()[0]
                return Scenario.from_name(name)
    return None


# ---------------------------------------------------------------------------
# Response builders
# ---------------------------------------------------------------------------

DEFAULT_USAGE = {"input_tokens": 10, "output_tokens": 6, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
TOOL_USAGE = {"input_tokens": 10, "output_tokens": 3, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}


def text_message_response(text: str = "Hello! How can I help you today?", model: str = "claude-sonnet-4-6") -> dict[str, Any]:
    """Build a non-streaming text response."""
    return {
        "id": "msg_mock_001",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "model": model,
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": DEFAULT_USAGE,
    }


def tool_message_response(
    tool_name: str,
    tool_id: str = "toolu_mock_001",
    tool_input: dict[str, Any] | None = None,
    model: str = "claude-sonnet-4-6",
) -> dict[str, Any]:
    """Build a non-streaming tool-use response."""
    return {
        "id": "msg_mock_002",
        "type": "message",
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": tool_id,
            "name": tool_name,
            "input": tool_input or {},
        }],
        "model": model,
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": TOOL_USAGE,
    }


# ---------------------------------------------------------------------------
# SSE event builders
# ---------------------------------------------------------------------------

def sse_event(event_type: str, data: dict[str, Any]) -> str:
    """Format a single SSE event."""
    return f"event: {event_type}\ndata: {json.dumps(data)}\n\n"


def streaming_text_sse(text: str = "Hello! How can I help you today?", model: str = "claude-sonnet-4-6") -> str:
    """Build SSE stream for a simple text response."""
    # Split text into chunks
    mid = len(text) // 2
    chunk1 = text[:mid]
    chunk2 = text[mid:]

    events = [
        sse_event("message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_mock_001",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 10, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            }
        }),
        sse_event("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        }),
        sse_event("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": chunk1},
        }),
        sse_event("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": chunk2},
        }),
        sse_event("content_block_stop", {
            "type": "content_block_stop",
            "index": 0,
        }),
        sse_event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 6},
        }),
        sse_event("message_stop", {"type": "message_stop"}),
    ]
    return "".join(events)


def tool_use_sse(
    tool_name: str,
    tool_id: str = "toolu_mock_001",
    tool_input: dict[str, Any] | None = None,
    model: str = "claude-sonnet-4-6",
) -> str:
    """Build SSE stream for a tool use response."""
    input_json = json.dumps(tool_input or {})
    # Split input JSON for chunked delivery
    mid = len(input_json) // 2
    chunk1 = input_json[:mid]
    chunk2 = input_json[mid:]

    events = [
        sse_event("message_start", {
            "type": "message_start",
            "message": {
                "id": "msg_mock_002",
                "type": "message",
                "role": "assistant",
                "content": [],
                "model": model,
                "stop_reason": None,
                "usage": {"input_tokens": 10, "output_tokens": 0, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
            }
        }),
        sse_event("content_block_start", {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "tool_use", "id": tool_id, "name": tool_name, "input": {}},
        }),
        sse_event("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": chunk1},
        }),
        sse_event("content_block_delta", {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": chunk2},
        }),
        sse_event("content_block_stop", {"type": "content_block_stop", "index": 0}),
        sse_event("message_delta", {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 3},
        }),
        sse_event("message_stop", {"type": "message_stop"}),
    ]
    return "".join(events)


def build_scenario_response(scenario: Scenario, request: dict[str, Any], stream: bool) -> str | dict[str, Any]:
    """Build response for a given scenario."""
    messages = request.get("messages", [])
    has_tool_results = any(
        any(b.get("type") == "tool_result" for b in msg.get("content", []) if isinstance(b, dict))
        for msg in messages
    )

    match scenario:
        case Scenario.STREAMING_TEXT:
            if stream:
                return streaming_text_sse()
            return text_message_response()

        case Scenario.READ_FILE_ROUNDTRIP:
            if has_tool_results:
                if stream:
                    return streaming_text_sse("I read the file successfully.")
                return text_message_response("I read the file successfully.")
            if stream:
                return tool_use_sse("Read", "toolu_read_001", {"file_path": "/tmp/test.txt"})
            return tool_message_response("Read", "toolu_read_001", {"file_path": "/tmp/test.txt"})

        case Scenario.BASH_STDOUT_ROUNDTRIP:
            if has_tool_results:
                if stream:
                    return streaming_text_sse("The command executed successfully.")
                return text_message_response("The command executed successfully.")
            if stream:
                return tool_use_sse("Bash", "toolu_bash_001", {"command": "echo hello"})
            return tool_message_response("Bash", "toolu_bash_001", {"command": "echo hello"})

        case Scenario.WRITE_FILE_ALLOWED:
            if has_tool_results:
                if stream:
                    return streaming_text_sse("File written successfully.")
                return text_message_response("File written successfully.")
            if stream:
                return tool_use_sse("Write", "toolu_write_001", {"file_path": "/tmp/out.txt", "content": "hello"})
            return tool_message_response("Write", "toolu_write_001", {"file_path": "/tmp/out.txt", "content": "hello"})

        case Scenario.TOKEN_COST_REPORTING:
            usage = {"input_tokens": 1_000_000, "output_tokens": 500_000, "cache_creation_input_tokens": 100_000, "cache_read_input_tokens": 200_000}
            resp = text_message_response("Cost report generated.")
            resp["usage"] = usage
            if stream:
                return streaming_text_sse("Cost report generated.")
            return resp

        case _:
            # Default: simple text response
            if stream:
                return streaming_text_sse(f"[{scenario.value}] Response")
            return text_message_response(f"[{scenario.value}] Response")
