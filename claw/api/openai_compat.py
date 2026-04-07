"""OpenAI-compatible API client with streaming support.

Maps to: rust/crates/api/src/providers/openai_compat.rs

Supports xAI (Grok) and OpenAI providers via the OpenAI chat completions
API format, translating between Anthropic-style request/response types and
OpenAI's wire format.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from claw.api.error import (
    ApiError,
    ApiResponseError,
    BackoffOverflowError,
    HttpError,
    InvalidSseFrameError,
    MissingCredentialsError,
    RetriesExhaustedError,
)
from claw.api.types import (
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputContentBlock,
    InputJsonDelta,
    InputMessage,
    MessageDelta,
    MessageDeltaEvent,
    MessageRequest,
    MessageResponse,
    MessageStartEvent,
    MessageStopEvent,
    OutputContentBlock,
    StreamEvent,
    TextDelta,
    TextInputBlock,
    TextOutputBlock,
    ToolChoice,
    ToolDefinition,
    ToolResultBlock,
    ToolResultJsonContent,
    ToolResultTextContent,
    ToolUseInputBlock,
    ToolUseOutputBlock,
    Usage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
REQUEST_ID_HEADER = "request-id"
ALT_REQUEST_ID_HEADER = "x-request-id"
DEFAULT_INITIAL_BACKOFF_MS = 200
DEFAULT_MAX_BACKOFF_MS = 2000
DEFAULT_MAX_RETRIES = 2
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


# ---------------------------------------------------------------------------
# Config presets
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class OpenAiCompatConfig:
    """Provider configuration for an OpenAI-compatible endpoint."""

    provider_name: str
    api_key_env: str
    base_url_env: str
    default_base_url: str

    @classmethod
    def xai(cls) -> OpenAiCompatConfig:
        return cls(
            provider_name="xAI",
            api_key_env="XAI_API_KEY",
            base_url_env="XAI_BASE_URL",
            default_base_url=DEFAULT_XAI_BASE_URL,
        )

    @classmethod
    def openai(cls) -> OpenAiCompatConfig:
        return cls(
            provider_name="OpenAI",
            api_key_env="OPENAI_API_KEY",
            base_url_env="OPENAI_BASE_URL",
            default_base_url=DEFAULT_OPENAI_BASE_URL,
        )

    @property
    def credential_env_vars(self) -> list[str]:
        return [self.api_key_env]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OpenAiCompatClient:
    """HTTP client for OpenAI-compatible chat completion APIs.

    Maps to: rust OpenAiCompatClient
    """

    def __init__(
        self,
        api_key: str,
        config: OpenAiCompatConfig,
        *,
        base_url: str | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS,
        max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS,
    ) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(120.0))
        self._api_key = api_key
        self._config = config
        self._base_url = base_url or _read_base_url(config)
        self._max_retries = max_retries
        self._initial_backoff_ms = initial_backoff_ms
        self._max_backoff_ms = max_backoff_ms

    @classmethod
    def from_env(cls, config: OpenAiCompatConfig) -> OpenAiCompatClient:
        """Create a client reading the API key from the environment."""
        api_key = _read_env_non_empty(config.api_key_env)
        if api_key is None:
            raise MissingCredentialsError(
                provider=config.provider_name,
                env_vars=config.credential_env_vars,
            )
        return cls(api_key=api_key, config=config)

    @property
    def config(self) -> OpenAiCompatConfig:
        return self._config

    # -- Public API ----------------------------------------------------------

    async def send_message(self, request: MessageRequest) -> MessageResponse:
        """Send a non-streaming chat completion request."""
        req = MessageRequest(
            model=request.model,
            max_tokens=request.max_tokens,
            messages=request.messages,
            system=request.system,
            tools=request.tools,
            tool_choice=request.tool_choice,
            stream=False,
        )
        response = await self._send_with_retry(req)
        request_id = _request_id_from_headers(response.headers)
        payload = response.json()
        normalized = _normalize_response(req.model, payload)
        if normalized.request_id is None:
            normalized.request_id = request_id
        return normalized

    async def stream_message(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        """Send a streaming request and yield Anthropic-format StreamEvents."""
        req = MessageRequest(
            model=request.model,
            max_tokens=request.max_tokens,
            messages=request.messages,
            system=request.system,
            tools=request.tools,
            tool_choice=request.tool_choice,
            stream=True,
        )
        response = await self._send_with_retry(req)
        request_id = _request_id_from_headers(response.headers)

        parser = OpenAiSseParser()
        state = _StreamState(model=req.model)

        async for raw_chunk in response.aiter_bytes():
            for chunk in parser.push(raw_chunk):
                for event in state.ingest_chunk(chunk):
                    yield event

        # Finalize the stream
        for event in state.finish():
            yield event

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()

    # -- Retry logic ---------------------------------------------------------

    async def _send_with_retry(self, request: MessageRequest) -> httpx.Response:
        attempts = 0
        last_error: ApiError | None = None

        while True:
            attempts += 1
            try:
                response = await self._send_raw_request(request)
                _expect_success(response)
                return response
            except ApiError as err:
                if err.is_retryable() and attempts <= self._max_retries:
                    last_error = err
                    backoff = self._backoff_for_attempt(attempts)
                    await asyncio.sleep(backoff)
                    continue
                if not err.is_retryable():
                    raise
                last_error = err
                break

        raise RetriesExhaustedError(attempts=attempts, last_error=last_error)  # type: ignore[arg-type]

    async def _send_raw_request(self, request: MessageRequest) -> httpx.Response:
        url = _chat_completions_endpoint(self._base_url)
        body = _build_chat_completion_request(request, self._config)
        try:
            response = await self._http.post(
                url,
                json=body,
                headers={
                    "content-type": "application/json",
                    "authorization": f"Bearer {self._api_key}",
                },
            )
            return response
        except httpx.HTTPError as exc:
            raise HttpError(str(exc), cause=exc) from exc

    def _backoff_for_attempt(self, attempt: int) -> float:
        """Exponential backoff in seconds."""
        try:
            multiplier = 1 << (attempt - 1)
        except (OverflowError, ValueError):
            raise BackoffOverflowError(attempt=attempt, base_delay_ms=self._initial_backoff_ms)

        delay_ms = self._initial_backoff_ms * multiplier
        delay_ms = min(delay_ms, self._max_backoff_ms)
        return delay_ms / 1000.0


# ---------------------------------------------------------------------------
# SSE parser (OpenAI format)
# ---------------------------------------------------------------------------

class OpenAiSseParser:
    """Incremental SSE parser for OpenAI's streaming format.

    Parses ``data: {...}\\n\\n`` frames and ``data: [DONE]`` terminators.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def push(self, chunk: bytes) -> list[dict[str, Any]]:
        """Push raw bytes and return any fully-parsed ChatCompletionChunk dicts."""
        self._buffer.extend(chunk)
        results: list[dict[str, Any]] = []

        while True:
            frame = self._next_frame()
            if frame is None:
                break
            parsed = _parse_sse_frame(frame)
            if parsed is not None:
                results.append(parsed)

        return results

    def _next_frame(self) -> str | None:
        pos = self._buffer.find(b"\n\n")
        sep_len = 2
        if pos == -1:
            pos = self._buffer.find(b"\r\n\r\n")
            sep_len = 4
        if pos == -1:
            return None

        frame_bytes = bytes(self._buffer[:pos])
        del self._buffer[:pos + sep_len]
        return frame_bytes.decode("utf-8", errors="replace")


def _parse_sse_frame(frame: str) -> dict[str, Any] | None:
    """Parse a single SSE frame into a ChatCompletionChunk dict."""
    trimmed = frame.strip()
    if not trimmed:
        return None

    data_lines: list[str] = []
    for line in trimmed.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:"):].lstrip())

    if not data_lines:
        return None

    payload = "\n".join(data_lines)
    if payload == "[DONE]":
        return None

    try:
        return json.loads(payload)
    except json.JSONDecodeError as exc:
        raise InvalidSseFrameError(f"Invalid JSON in SSE data: {exc}") from exc


# ---------------------------------------------------------------------------
# Stream state machine
# ---------------------------------------------------------------------------

class _ToolCallState:
    """Accumulates streamed tool call deltas for a single tool call."""

    __slots__ = ("openai_index", "id", "name", "arguments", "emitted_len", "started", "stopped")

    def __init__(self, openai_index: int = 0) -> None:
        self.openai_index = openai_index
        self.id: str | None = None
        self.name: str | None = None
        self.arguments: str = ""
        self.emitted_len: int = 0
        self.started: bool = False
        self.stopped: bool = False

    def apply(self, tool_call: dict[str, Any]) -> None:
        self.openai_index = tool_call.get("index", self.openai_index)
        if "id" in tool_call and tool_call["id"]:
            self.id = tool_call["id"]
        func = tool_call.get("function", {})
        if func.get("name"):
            self.name = func["name"]
        if func.get("arguments"):
            self.arguments += func["arguments"]

    @property
    def block_index(self) -> int:
        """Anthropic block index: tool calls start after the text block at 0."""
        return self.openai_index + 1

    def start_event(self) -> ContentBlockStartEvent | None:
        if self.name is None:
            return None
        tool_id = self.id or f"tool_call_{self.openai_index}"
        return ContentBlockStartEvent(
            index=self.block_index,
            content_block=ToolUseOutputBlock(id=tool_id, name=self.name, input={}),
        )

    def delta_event(self) -> ContentBlockDeltaEvent | None:
        if self.emitted_len >= len(self.arguments):
            return None
        delta_text = self.arguments[self.emitted_len:]
        self.emitted_len = len(self.arguments)
        return ContentBlockDeltaEvent(
            index=self.block_index,
            delta=InputJsonDelta(partial_json=delta_text),
        )


class _StreamState:
    """Translates a sequence of OpenAI ChatCompletionChunks into Anthropic StreamEvents."""

    def __init__(self, model: str) -> None:
        self._model = model
        self._message_started = False
        self._text_started = False
        self._text_finished = False
        self._finished = False
        self._stop_reason: str | None = None
        self._usage: Usage | None = None
        self._tool_calls: OrderedDict[int, _ToolCallState] = OrderedDict()

    def ingest_chunk(self, chunk: dict[str, Any]) -> list[StreamEvent]:
        """Process one ChatCompletionChunk dict and return resulting StreamEvents."""
        events: list[StreamEvent] = []

        # Emit MessageStart on first chunk
        if not self._message_started:
            self._message_started = True
            events.append(MessageStartEvent(
                message=MessageResponse(
                    id=chunk.get("id", ""),
                    type="message",
                    role="assistant",
                    content=[],
                    model=chunk.get("model") or self._model,
                    usage=Usage(),
                ),
            ))

        # Track usage if present
        if "usage" in chunk and chunk["usage"]:
            u = chunk["usage"]
            self._usage = Usage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
            )

        # Process choices
        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})

            # Text content
            content = delta.get("content")
            if content:
                if not self._text_started:
                    self._text_started = True
                    events.append(ContentBlockStartEvent(
                        index=0,
                        content_block=TextOutputBlock(text=""),
                    ))
                events.append(ContentBlockDeltaEvent(
                    index=0,
                    delta=TextDelta(text=content),
                ))

            # Tool calls
            for tc in delta.get("tool_calls", []):
                idx = tc.get("index", 0)
                if idx not in self._tool_calls:
                    self._tool_calls[idx] = _ToolCallState(openai_index=idx)
                state = self._tool_calls[idx]
                state.apply(tc)

                if not state.started:
                    start_ev = state.start_event()
                    if start_ev is not None:
                        state.started = True
                        events.append(start_ev)
                    else:
                        continue

                delta_ev = state.delta_event()
                if delta_ev is not None:
                    events.append(delta_ev)

                if choice.get("finish_reason") == "tool_calls" and not state.stopped:
                    state.stopped = True
                    events.append(ContentBlockStopEvent(index=state.block_index))

            # Finish reason
            finish_reason = choice.get("finish_reason")
            if finish_reason:
                self._stop_reason = _normalize_finish_reason(finish_reason)
                if finish_reason == "tool_calls":
                    for state in self._tool_calls.values():
                        if state.started and not state.stopped:
                            state.stopped = True
                            events.append(ContentBlockStopEvent(index=state.block_index))

        return events

    def finish(self) -> list[StreamEvent]:
        """Finalize the stream, emitting closing events."""
        if self._finished:
            return []
        self._finished = True

        events: list[StreamEvent] = []

        # Close text block if still open
        if self._text_started and not self._text_finished:
            self._text_finished = True
            events.append(ContentBlockStopEvent(index=0))

        # Flush any un-started or un-stopped tool calls
        for state in self._tool_calls.values():
            if not state.started:
                start_ev = state.start_event()
                if start_ev is not None:
                    state.started = True
                    events.append(start_ev)
                    delta_ev = state.delta_event()
                    if delta_ev is not None:
                        events.append(delta_ev)
            if state.started and not state.stopped:
                state.stopped = True
                events.append(ContentBlockStopEvent(index=state.block_index))

        # MessageDelta and MessageStop
        if self._message_started:
            events.append(MessageDeltaEvent(
                delta=MessageDelta(
                    stop_reason=self._stop_reason or "end_turn",
                ),
                usage=self._usage or Usage(),
            ))
            events.append(MessageStopEvent())

        return events


# ---------------------------------------------------------------------------
# Request translation (Anthropic -> OpenAI)
# ---------------------------------------------------------------------------

def _build_chat_completion_request(
    request: MessageRequest, config: OpenAiCompatConfig
) -> dict[str, Any]:
    """Translate an Anthropic-style MessageRequest into an OpenAI chat completion body."""
    messages: list[dict[str, Any]] = []

    # System message
    if request.system:
        messages.append({"role": "system", "content": request.system})

    # Conversation messages
    for message in request.messages:
        messages.extend(_translate_message(message))

    payload: dict[str, Any] = {
        "model": request.model,
        "max_tokens": request.max_tokens,
        "messages": messages,
        "stream": request.stream,
    }

    # OpenAI requires stream_options for usage in streaming
    if request.stream and _should_request_stream_usage(config):
        payload["stream_options"] = {"include_usage": True}

    # Tools
    if request.tools:
        payload["tools"] = [_openai_tool_definition(t) for t in request.tools]

    # Tool choice
    if request.tool_choice is not None:
        payload["tool_choice"] = _openai_tool_choice(request.tool_choice)

    return payload


def _translate_message(message: InputMessage) -> list[dict[str, Any]]:
    """Translate a single Anthropic InputMessage into one or more OpenAI messages."""
    if message.role == "assistant":
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in message.content:
            if isinstance(block, TextInputBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseInputBlock):
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input) if not isinstance(block.input, str) else block.input,
                    },
                })
        text = "".join(text_parts)
        if not text and not tool_calls:
            return []
        msg: dict[str, Any] = {"role": "assistant"}
        if text:
            msg["content"] = text
        if tool_calls:
            msg["tool_calls"] = tool_calls
        return [msg]

    # User or other roles: expand each block into its own message
    results: list[dict[str, Any]] = []
    for block in message.content:
        if isinstance(block, TextInputBlock):
            results.append({"role": "user", "content": block.text})
        elif isinstance(block, ToolResultBlock):
            content = _flatten_tool_result_content(block)
            results.append({
                "role": "tool",
                "tool_call_id": block.tool_use_id,
                "content": content,
            })
    return results


def _flatten_tool_result_content(block: ToolResultBlock) -> str:
    """Flatten tool result content blocks into a single string."""
    parts: list[str] = []
    for c in block.content:
        if isinstance(c, ToolResultTextContent):
            parts.append(c.text)
        elif isinstance(c, ToolResultJsonContent):
            parts.append(json.dumps(c.value) if not isinstance(c.value, str) else c.value)
    return "\n".join(parts)


def _openai_tool_definition(tool: ToolDefinition) -> dict[str, Any]:
    """Translate an Anthropic ToolDefinition to OpenAI function format."""
    func: dict[str, Any] = {
        "name": tool.name,
        "parameters": tool.input_schema,
    }
    if tool.description is not None:
        func["description"] = tool.description
    return {"type": "function", "function": func}


def _openai_tool_choice(tool_choice: ToolChoice) -> Any:
    """Translate Anthropic ToolChoice to OpenAI tool_choice format."""
    if tool_choice.type == "auto":
        return "auto"
    if tool_choice.type == "any":
        return "required"
    if tool_choice.type == "tool" and tool_choice.name:
        return {"type": "function", "function": {"name": tool_choice.name}}
    return "auto"


# ---------------------------------------------------------------------------
# Response translation (OpenAI -> Anthropic)
# ---------------------------------------------------------------------------

def _normalize_response(model: str, data: dict[str, Any]) -> MessageResponse:
    """Translate an OpenAI ChatCompletion response to Anthropic MessageResponse."""
    choices = data.get("choices", [])
    if not choices:
        raise InvalidSseFrameError("chat completion response missing choices")

    choice = choices[0]
    message = choice.get("message", {})
    content: list[OutputContentBlock] = []

    # Text content
    text = message.get("content")
    if text:
        content.append(TextOutputBlock(text=text))

    # Tool calls
    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        arguments = _parse_tool_arguments(func.get("arguments", ""))
        content.append(ToolUseOutputBlock(
            id=tc.get("id", ""),
            name=func.get("name", ""),
            input=arguments,
        ))

    # Usage
    usage_data = data.get("usage", {})
    usage = Usage(
        input_tokens=usage_data.get("prompt_tokens", 0),
        output_tokens=usage_data.get("completion_tokens", 0),
    )

    # Finish reason
    finish_reason = choice.get("finish_reason")
    stop_reason = _normalize_finish_reason(finish_reason) if finish_reason else None

    resp_model = data.get("model", "") or model

    return MessageResponse(
        id=data.get("id", ""),
        type="message",
        role=message.get("role", "assistant"),
        content=content,
        model=resp_model,
        usage=usage,
        stop_reason=stop_reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_tool_arguments(arguments: str) -> Any:
    """Parse tool call arguments JSON, falling back to a raw wrapper."""
    try:
        return json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {"raw": arguments}


def _normalize_finish_reason(value: str) -> str:
    """Map OpenAI finish reasons to Anthropic stop reasons."""
    mapping = {"stop": "end_turn", "tool_calls": "tool_use"}
    return mapping.get(value, value)


def _should_request_stream_usage(config: OpenAiCompatConfig) -> bool:
    """Only OpenAI proper requires the stream_options usage opt-in."""
    return config.provider_name == "OpenAI"


def _chat_completions_endpoint(base_url: str) -> str:
    """Build the chat/completions URL, handling trailing slashes and full URLs."""
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _read_env_non_empty(key: str) -> str | None:
    """Read an environment variable, returning None if empty or unset."""
    value = os.environ.get(key, "")
    return value if value else None


def _read_base_url(config: OpenAiCompatConfig) -> str:
    """Read the base URL from env or fall back to the default."""
    return os.environ.get(config.base_url_env, "") or config.default_base_url


def _request_id_from_headers(headers: httpx.Headers) -> str | None:
    """Extract request ID from response headers."""
    return headers.get(REQUEST_ID_HEADER) or headers.get(ALT_REQUEST_ID_HEADER)


def _expect_success(response: httpx.Response) -> None:
    """Raise ApiResponseError for non-2xx responses."""
    if response.is_success:
        return

    request_id = _request_id_from_headers(response.headers)
    body = response.text

    error_type: str | None = None
    message: str | None = None
    try:
        envelope = json.loads(body)
        err_obj = envelope.get("error", {})
        error_type = err_obj.get("type")
        message = err_obj.get("message")
    except (json.JSONDecodeError, AttributeError):
        pass

    retryable = response.status_code in RETRYABLE_STATUS_CODES

    raise ApiResponseError(
        status=response.status_code,
        error_type=error_type,
        message=message,
        request_id_val=request_id,
        body=body,
        retryable=retryable,
    )


def has_api_key(key: str) -> bool:
    """Check whether an API key environment variable is set and non-empty."""
    return _read_env_non_empty(key) is not None
