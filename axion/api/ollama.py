"""Ollama-compatible API client with streaming support.

Ollama runs locally and exposes an OpenAI-compatible API at
http://localhost:11434/v1/chat/completions.  This module provides a
client that translates between Anthropic-style request/response types
and the Ollama wire format.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from axion.api.error import (
    ApiResponseError,
    HttpError,
    InvalidSseFrameError,
)
from axion.api.types import (
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
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
    ToolUseOutputBlock,
    Usage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "llama3.1"
OLLAMA_BASE_URL_ENV = "OLLAMA_BASE_URL"

# Prefixes that indicate an Ollama / local model
OLLAMA_MODEL_PREFIXES = (
    "llama",
    "mistral",
    "codellama",
    "deepseek",
    "phi",
    "gemma",
    "qwen",
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass
class OllamaModelInfo:
    """Summary of a locally-available Ollama model."""

    name: str
    size: int = 0
    digest: str = ""
    modified_at: str = ""
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SSE parser (OpenAI format, reused from openai_compat logic)
# ---------------------------------------------------------------------------


class _OllamaSseParser:
    """Incremental SSE parser for Ollama's OpenAI-compatible streaming."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def push(self, chunk: bytes) -> list[dict[str, Any]]:
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
        del self._buffer[: pos + sep_len]
        return frame_bytes.decode("utf-8", errors="replace")


def _parse_sse_frame(frame: str) -> dict[str, Any] | None:
    trimmed = frame.strip()
    if not trimmed:
        return None

    data_lines: list[str] = []
    for line in trimmed.splitlines():
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[len("data:") :].lstrip())

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


class _OllamaStreamState:
    """Translates OpenAI ChatCompletionChunks into Anthropic StreamEvents.

    Simplified compared to the full OpenAI compat state machine: Ollama does
    not currently emit ``tool_calls`` deltas in streaming mode, so tool-call
    accumulation is omitted.
    """

    def __init__(self, model: str) -> None:
        self._model = model
        self._message_started = False
        self._text_started = False
        self._text_finished = False
        self._finished = False
        self._stop_reason: str | None = None
        self._usage: Usage | None = None

    def ingest_chunk(self, chunk: dict[str, Any]) -> list[StreamEvent]:
        events: list[StreamEvent] = []

        if not self._message_started:
            self._message_started = True
            events.append(
                MessageStartEvent(
                    message=MessageResponse(
                        id=chunk.get("id", ""),
                        type="message",
                        role="assistant",
                        content=[],
                        model=chunk.get("model") or self._model,
                        usage=Usage(),
                    ),
                )
            )

        if "usage" in chunk and chunk["usage"]:
            u = chunk["usage"]
            self._usage = Usage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
            )

        for choice in chunk.get("choices", []):
            delta = choice.get("delta", {})

            content = delta.get("content")
            if content:
                if not self._text_started:
                    self._text_started = True
                    events.append(
                        ContentBlockStartEvent(
                            index=0,
                            content_block=TextOutputBlock(text=""),
                        )
                    )
                events.append(
                    ContentBlockDeltaEvent(
                        index=0,
                        delta=TextDelta(text=content),
                    )
                )

            finish_reason = choice.get("finish_reason")
            if finish_reason:
                self._stop_reason = _normalize_finish_reason(finish_reason)

        return events

    def finish(self) -> list[StreamEvent]:
        if self._finished:
            return []
        self._finished = True

        events: list[StreamEvent] = []

        if self._text_started and not self._text_finished:
            self._text_finished = True
            events.append(ContentBlockStopEvent(index=0))

        if self._message_started:
            events.append(
                MessageDeltaEvent(
                    delta=MessageDelta(
                        stop_reason=self._stop_reason or "end_turn",
                    ),
                    usage=self._usage or Usage(),
                )
            )
            events.append(MessageStopEvent())

        return events


# ---------------------------------------------------------------------------
# Request translation (Anthropic -> Ollama / OpenAI)
# ---------------------------------------------------------------------------


def _build_ollama_request(request: MessageRequest) -> dict[str, Any]:
    """Translate an Anthropic-style MessageRequest into an OpenAI chat body."""
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

    # Tools -> OpenAI functions format
    if request.tools:
        payload["tools"] = [_openai_tool_definition(t) for t in request.tools]

    if request.tool_choice is not None:
        payload["tool_choice"] = _openai_tool_choice(request.tool_choice)

    return payload


def _translate_message(message: InputMessage) -> list[dict[str, Any]]:
    """Translate a single Anthropic InputMessage into OpenAI messages."""
    if message.role == "assistant":
        text_parts: list[str] = []
        for block in message.content:
            if isinstance(block, TextInputBlock):
                text_parts.append(block.text)
        text = "".join(text_parts)
        if not text:
            return []
        return [{"role": "assistant", "content": text}]

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
    parts: list[str] = []
    for c in block.content:
        if isinstance(c, ToolResultTextContent):
            parts.append(c.text)
        elif isinstance(c, ToolResultJsonContent):
            parts.append(
                json.dumps(c.value) if not isinstance(c.value, str) else c.value
            )
    return "\n".join(parts)


def _openai_tool_definition(tool: ToolDefinition) -> dict[str, Any]:
    func: dict[str, Any] = {
        "name": tool.name,
        "parameters": tool.input_schema,
    }
    if tool.description is not None:
        func["description"] = tool.description
    return {"type": "function", "function": func}


def _openai_tool_choice(tool_choice: ToolChoice) -> Any:
    if tool_choice.type == "auto":
        return "auto"
    if tool_choice.type == "any":
        return "required"
    if tool_choice.type == "tool" and tool_choice.name:
        return {"type": "function", "function": {"name": tool_choice.name}}
    return "auto"


# ---------------------------------------------------------------------------
# Response translation (Ollama / OpenAI -> Anthropic)
# ---------------------------------------------------------------------------


def _normalize_response(model: str, data: dict[str, Any]) -> MessageResponse:
    """Translate an OpenAI ChatCompletion response to Anthropic MessageResponse."""
    choices = data.get("choices", [])
    if not choices:
        raise InvalidSseFrameError("chat completion response missing choices")

    choice = choices[0]
    message = choice.get("message", {})
    content: list[OutputContentBlock] = []

    text = message.get("content")
    if text:
        content.append(TextOutputBlock(text=text))

    # Tool calls (Ollama may include these in non-streaming mode)
    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        arguments = _parse_tool_arguments(func.get("arguments", ""))
        content.append(
            ToolUseOutputBlock(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                input=arguments,
            )
        )

    usage_data = data.get("usage", {})
    usage = Usage(
        input_tokens=usage_data.get("prompt_tokens", 0),
        output_tokens=usage_data.get("completion_tokens", 0),
    )

    finish_reason = choice.get("finish_reason")
    stop_reason = _normalize_finish_reason(finish_reason) if finish_reason else None

    return MessageResponse(
        id=data.get("id", ""),
        type="message",
        role=message.get("role", "assistant"),
        content=content,
        model=data.get("model", "") or model,
        usage=usage,
        stop_reason=stop_reason,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_tool_arguments(arguments: str) -> Any:
    try:
        return json.loads(arguments)
    except (json.JSONDecodeError, TypeError):
        return {"raw": arguments}


def _normalize_finish_reason(value: str) -> str:
    mapping = {"stop": "end_turn", "tool_calls": "tool_use"}
    return mapping.get(value, value)


def _read_ollama_base_url() -> str:
    return os.environ.get(OLLAMA_BASE_URL_ENV, "") or DEFAULT_OLLAMA_BASE_URL


def is_ollama_model(model: str) -> bool:
    """Return True if *model* looks like a locally-served Ollama model."""
    lower = model.lower()
    return any(lower.startswith(prefix) for prefix in OLLAMA_MODEL_PREFIXES)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class OllamaClient:
    """HTTP client for a local Ollama instance.

    Ollama exposes an OpenAI-compatible endpoint at ``/v1/chat/completions``
    and a native tag-listing endpoint at ``/api/tags``.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        model: str = DEFAULT_OLLAMA_MODEL,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(300.0))

    @classmethod
    def from_env(cls, model: str | None = None) -> OllamaClient:
        """Create a client using environment variables for the base URL."""
        base_url = _read_ollama_base_url()
        return cls(base_url=base_url, model=model or DEFAULT_OLLAMA_MODEL)

    @property
    def model(self) -> str:
        return self._model

    @property
    def base_url(self) -> str:
        return self._base_url

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
        body = _build_ollama_request(req)
        url = f"{self._base_url}/v1/chat/completions"

        try:
            response = await self._http.post(
                url,
                json=body,
                headers={"content-type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise HttpError(str(exc), cause=exc) from exc

        _expect_success(response)
        payload = response.json()
        return _normalize_response(req.model, payload)

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
        body = _build_ollama_request(req)
        url = f"{self._base_url}/v1/chat/completions"

        try:
            response = await self._http.send(
                self._http.build_request(
                    "POST",
                    url,
                    json=body,
                    headers={"content-type": "application/json"},
                ),
                stream=True,
            )
        except httpx.HTTPError as exc:
            raise HttpError(str(exc), cause=exc) from exc

        if not response.is_success:
            body_text = await response.aread()
            raise ApiResponseError(
                status=response.status_code,
                body=body_text.decode("utf-8", errors="replace"),
            )

        parser = _OllamaSseParser()
        state = _OllamaStreamState(model=req.model)

        async for raw_chunk in response.aiter_bytes():
            for chunk in parser.push(raw_chunk):
                for event in state.ingest_chunk(chunk):
                    yield event

        for event in state.finish():
            yield event

    async def list_models(self) -> list[OllamaModelInfo]:
        """GET /api/tags -- list locally available models."""
        url = f"{self._base_url}/api/tags"
        try:
            response = await self._http.get(url)
        except httpx.HTTPError as exc:
            raise HttpError(str(exc), cause=exc) from exc

        _expect_success(response)
        data = response.json()

        models: list[OllamaModelInfo] = []
        for m in data.get("models", []):
            models.append(
                OllamaModelInfo(
                    name=m.get("name", ""),
                    size=m.get("size", 0),
                    digest=m.get("digest", ""),
                    modified_at=m.get("modified_at", ""),
                    details=m.get("details", {}),
                )
            )
        return models

    async def is_available(self) -> bool:
        """Check whether the Ollama server is reachable."""
        url = f"{self._base_url}/api/tags"
        try:
            response = await self._http.get(url, timeout=httpx.Timeout(5.0))
            return response.is_success
        except (httpx.HTTPError, OSError):
            return False

    async def close(self) -> None:
        """Shut down the underlying HTTP client."""
        await self._http.aclose()


# ---------------------------------------------------------------------------
# Response validation
# ---------------------------------------------------------------------------


def _expect_success(response: httpx.Response) -> None:
    """Raise ApiResponseError for non-2xx responses."""
    if response.is_success:
        return

    body = response.text

    error_type: str | None = None
    message: str | None = None
    try:
        envelope = json.loads(body)
        err_obj = envelope.get("error", {})
        if isinstance(err_obj, dict):
            error_type = err_obj.get("type")
            message = err_obj.get("message")
        elif isinstance(err_obj, str):
            message = err_obj
    except (json.JSONDecodeError, AttributeError):
        pass

    raise ApiResponseError(
        status=response.status_code,
        error_type=error_type,
        message=message,
        body=body,
    )
