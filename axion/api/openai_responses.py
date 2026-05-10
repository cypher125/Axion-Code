"""OpenAI Responses API client (the /v1/responses endpoint, used by Codex).

Maps to: rust/crates/api/src/providers/openai_responses.rs (no equivalent yet)

The Responses API differs from Chat Completions:
  - Single `input` array instead of `messages` (each item has type+content blocks)
  - Stateful by default (`previous_response_id`); we use stateless mode (`store: false`)
  - Reasoning settings via `reasoning: {effort: "low|medium|high"}`
  - Different streaming events (`response.created`, `response.output_text.delta`,
    `response.output_item.added`, `response.completed`, etc.)
  - Tools format is similar to Chat Completions but slightly different field names

This client translates between Anthropic-style MessageRequest/StreamEvent
(what the rest of axion uses) and the Responses API wire format.

Used by Codex models (gpt-5-codex, gpt-5-codex-mini, codex, codex-mini).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from axion.api.error import (
    ApiError,
    ApiResponseError,
    BackoffOverflowError,
    HttpError,
    MissingCredentialsError,
    RetriesExhaustedError,
)
from axion.api.openai_compat import OpenAiSseParser
from axion.api.types import (
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    ImageInputBlock,
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
    ToolDefinition,
    ToolResultBlock,
    ToolUseInputBlock,
    ToolUseOutputBlock,
    Usage,
)

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MAX_RETRIES = 3
DEFAULT_INITIAL_BACKOFF_MS = 1000
DEFAULT_MAX_BACKOFF_MS = 30000


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class OpenAiResponsesClient:
    """HTTP client for OpenAI's /v1/responses endpoint (Codex models)."""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        max_retries: int = DEFAULT_MAX_RETRIES,
        initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS,
        max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS,
        bearer_override: str | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=30.0))
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._initial_backoff_ms = initial_backoff_ms
        self._max_backoff_ms = max_backoff_ms
        # Optional Bearer token override (for ChatGPT subscription OAuth, future)
        self._bearer_override = bearer_override

    @classmethod
    def from_env(cls) -> OpenAiResponsesClient:
        """Create a client using ChatGPT subscription if present, else API key.

        Resolution order (unless AXION_AUTH_MODE=api forces API):
          1. ChatGPT subscription OAuth token (~/.axion/credentials/openai-oauth.json)
          2. OPENAI_API_KEY env var
          3. ~/.axion/credentials/openai.key file
        """
        base = os.environ.get("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)
        auth_mode = os.environ.get("AXION_AUTH_MODE", "").lower()

        # 1. Try ChatGPT subscription unless explicitly forced to API mode
        if auth_mode != "api":
            try:
                from axion.runtime.openai_subscription import (
                    SUBSCRIPTION_PROVIDER,
                    has_openai_subscription_credentials,
                    load_oauth_credentials,
                )
                if has_openai_subscription_credentials():
                    creds = load_oauth_credentials(SUBSCRIPTION_PROVIDER)
                    if creds and creds.access_token:
                        # api_key still required by ctor; pass empty since
                        # bearer_override takes precedence.
                        return cls(
                            api_key="",
                            base_url=base,
                            bearer_override=creds.access_token,
                        )
            except Exception as exc:
                logger.debug("Subscription auth lookup failed: %s", exc)

        # 2. Fall back to API key
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            from pathlib import Path
            key_path = Path.home() / ".axion" / "credentials" / "openai.key"
            if key_path.exists():
                saved = key_path.read_text(encoding="utf-8").strip()
                if saved:
                    api_key = saved
                    os.environ["OPENAI_API_KEY"] = saved

        if not api_key:
            raise MissingCredentialsError(provider="OpenAI", env_vars=["OPENAI_API_KEY"])

        return cls(api_key=api_key, base_url=base)

    # -- Public API ----------------------------------------------------------

    async def send_message(self, request: MessageRequest) -> MessageResponse:
        """Send a non-streaming Responses API request."""
        req = _clone_request(request, stream=False)
        response = await self._send_with_retry(req)
        payload = response.json()
        return _normalize_response(req.model, payload)

    async def stream_message(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        """Stream a Responses API request, converting events to the standard format."""
        req = _clone_request(request, stream=True)
        response = await self._send_with_retry(req)

        parser = OpenAiSseParser()
        state = _ResponsesStreamState(model=req.model)

        async for raw_chunk in response.aiter_bytes():
            for chunk in parser.push(raw_chunk):
                for event in state.ingest_event(chunk):
                    yield event

        for event in state.finish():
            yield event

    async def close(self) -> None:
        await self._http.aclose()

    # -- Retry / send -------------------------------------------------------

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
                    await asyncio.sleep(self._backoff_for_attempt(attempts))
                    continue
                if not err.is_retryable():
                    raise
                last_error = err
                break
        raise RetriesExhaustedError(attempts=attempts, last_error=last_error)  # type: ignore[arg-type]

    async def _refresh_subscription_token_if_needed(self) -> None:
        """If using a subscription bearer, refresh it when near-expired."""
        if not self._bearer_override:
            return
        try:
            from axion.runtime.openai_subscription import (
                get_valid_openai_subscription_token,
            )
            new_token = await get_valid_openai_subscription_token()
            if new_token and new_token != self._bearer_override:
                self._bearer_override = new_token
                logger.info("Refreshed ChatGPT subscription token")
        except Exception as exc:
            logger.debug("Subscription token refresh check failed: %s", exc)

    async def _send_raw_request(self, request: MessageRequest) -> httpx.Response:
        await self._refresh_subscription_token_if_needed()
        url = f"{self._base_url}/responses"
        body = _build_responses_request(request)
        token = self._bearer_override or self._api_key
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {token}",
        }
        # Codex CLI sends an originator header so OpenAI knows which client
        # the request came from. Required for subscription-billed requests.
        if self._bearer_override:
            headers["openai-beta"] = "responses-2024-09-30"
            headers["originator"] = "codex_cli_rs"
        try:
            response = await self._http.post(
                url,
                json=body,
                headers=headers,
            )
            return response
        except httpx.HTTPError as exc:
            raise HttpError(str(exc), cause=exc) from exc

    def _backoff_for_attempt(self, attempt: int) -> float:
        try:
            multiplier = 1 << (attempt - 1)
        except (OverflowError, ValueError):
            raise BackoffOverflowError(attempt=attempt, base_delay_ms=self._initial_backoff_ms)
        delay_ms = min(self._initial_backoff_ms * multiplier, self._max_backoff_ms)
        return delay_ms / 1000.0


# ---------------------------------------------------------------------------
# Request builder: MessageRequest -> /v1/responses body
# ---------------------------------------------------------------------------

def _build_responses_request(request: MessageRequest) -> dict[str, Any]:
    """Translate an Anthropic-style MessageRequest to a Responses API body."""
    input_items: list[dict[str, Any]] = []

    # System prompt becomes the Responses API "instructions" field.
    # MessageRequest.system is typed as str|None, but at runtime it can also
    # be a list of text blocks (Anthropic prompt-caching format), so check both.
    instructions: str | None = None
    sys_value: Any = request.system
    if sys_value:
        if isinstance(sys_value, str):
            instructions = sys_value
        elif isinstance(sys_value, list):
            parts: list[str] = []
            for block in sys_value:
                if isinstance(block, dict):
                    parts.append(str(block.get("text", "")))
                else:
                    parts.append(str(block))
            instructions = "\n\n".join(p for p in parts if p)

    # Conversation messages
    for msg in request.messages:
        for item in _translate_message_to_input_items(msg):
            input_items.append(item)

    body: dict[str, Any] = {
        "model": request.model,
        "input": input_items,
        "stream": request.stream,
        "store": False,  # stateless — we manage history ourselves
    }
    if instructions:
        body["instructions"] = instructions
    if request.max_tokens:
        body["max_output_tokens"] = request.max_tokens

    # Tools
    if request.tools:
        body["tools"] = [_translate_tool_definition(t) for t in request.tools]

    # Codex models support reasoning effort
    if "codex" in request.model.lower() or request.model.startswith(("o1", "o3", "o4", "gpt-5")):
        body["reasoning"] = {"effort": "medium"}

    # Tool choice (ToolChoice.type is "auto" | "any" | "tool")
    if request.tool_choice is not None:
        tc = request.tool_choice
        if tc.type == "auto":
            body["tool_choice"] = "auto"
        elif tc.type == "any":
            body["tool_choice"] = "required"
        elif tc.type == "tool" and tc.name:
            body["tool_choice"] = {"type": "function", "name": tc.name}

    return body


def _translate_message_to_input_items(msg: InputMessage) -> list[dict[str, Any]]:
    """Translate one InputMessage to one or more Responses API input items."""
    if msg.role == "assistant":
        # Assistant messages may contain text + tool_use blocks
        parts: list[dict[str, Any]] = []
        for block in msg.content:
            if isinstance(block, TextInputBlock):
                parts.append({"type": "output_text", "text": block.text})
            elif isinstance(block, ToolUseInputBlock):
                # Responses API uses function_call for assistant tool requests
                parts.append({
                    "type": "function_call",
                    "call_id": block.id,
                    "name": block.name,
                    "arguments": (
                        json.dumps(block.input)
                        if not isinstance(block.input, str)
                        else block.input
                    ),
                })
        if not parts:
            return []
        return [{"type": "message", "role": "assistant", "content": parts}]

    # User / tool-result messages
    results: list[dict[str, Any]] = []
    user_content: list[dict[str, Any]] = []

    for block in msg.content:
        if isinstance(block, TextInputBlock):
            user_content.append({"type": "input_text", "text": block.text})
        elif isinstance(block, ImageInputBlock):
            user_content.append({
                "type": "input_image",
                "image_url": f"data:{block.media_type};base64,{block.data}",
            })
        elif isinstance(block, ToolResultBlock):
            # Tool results become function_call_output items
            results.append({
                "type": "function_call_output",
                "call_id": block.tool_use_id,
                "output": _flatten_tool_result_content(block),
            })

    if user_content:
        results.append({
            "type": "message",
            "role": "user",
            "content": user_content,
        })

    return results


def _flatten_tool_result_content(block: ToolResultBlock) -> str:
    """Concatenate tool result content blocks into a single string."""
    parts: list[str] = []
    for c in block.content:
        text = getattr(c, "text", None)
        if text is not None:
            parts.append(text)
        else:
            value = getattr(c, "value", None)
            if value is not None:
                parts.append(json.dumps(value) if not isinstance(value, str) else value)
    return "\n".join(parts) if parts else ""


def _translate_tool_definition(tool: ToolDefinition) -> dict[str, Any]:
    """Translate an Anthropic ToolDefinition to Responses API tool format."""
    return {
        "type": "function",
        "name": tool.name,
        "description": tool.description,
        "parameters": tool.input_schema,
    }


# ---------------------------------------------------------------------------
# Response normalization (non-streaming)
# ---------------------------------------------------------------------------

def _normalize_response(model: str, data: dict[str, Any]) -> MessageResponse:
    """Convert a /v1/responses payload to an Anthropic-style MessageResponse."""
    output = data.get("output", []) or []
    content_blocks: list[OutputContentBlock] = []

    for item in output:
        item_type = item.get("type", "")
        if item_type == "message":
            for part in item.get("content", []) or []:
                if part.get("type") == "output_text":
                    content_blocks.append(TextOutputBlock(text=part.get("text", "")))
        elif item_type == "function_call":
            args_str = item.get("arguments", "")
            try:
                args = json.loads(args_str) if args_str else {}
            except json.JSONDecodeError:
                args = {"raw": args_str}
            content_blocks.append(
                ToolUseOutputBlock(
                    id=item.get("call_id") or item.get("id", ""),
                    name=item.get("name", ""),
                    input=args,
                )
            )

    usage_data = data.get("usage", {}) or {}
    usage = Usage(
        input_tokens=usage_data.get("input_tokens", 0),
        output_tokens=usage_data.get("output_tokens", 0),
        cache_creation_input_tokens=0,
        cache_read_input_tokens=(usage_data.get("input_tokens_details", {}) or {}).get("cached_tokens", 0),
    )

    stop_reason = _map_stop_reason(data.get("status"))

    return MessageResponse(
        id=data.get("id", ""),
        type="message",
        role="assistant",
        content=content_blocks,
        model=data.get("model", model),
        usage=usage,
        stop_reason=stop_reason,
    )


def _map_stop_reason(status: str | None) -> str | None:
    if status == "completed":
        return "end_turn"
    if status == "incomplete":
        return "max_tokens"
    if status == "failed":
        return "error"
    return status


# ---------------------------------------------------------------------------
# Streaming: convert /v1/responses SSE events to the standard StreamEvent format
# ---------------------------------------------------------------------------

@dataclass
class _ResponsesStreamState:
    """Tracks the streaming state for a single response."""
    model: str
    response_id: str = ""
    started: bool = False
    # Maps output_index -> (block_index, kind, name)  for both text & function_call
    output_index_to_block: dict[int, tuple[int, str, str | None]] = field(default_factory=dict)
    next_block_index: int = 0
    accumulated_input_tokens: int = 0
    accumulated_output_tokens: int = 0
    cache_read_tokens: int = 0
    final_stop_reason: str | None = None

    def ingest_event(self, event: dict[str, Any]) -> list[StreamEvent]:
        """Process one parsed Responses API SSE event, emit StreamEvents."""
        evt_type = event.get("type", "")
        out: list[StreamEvent] = []

        if evt_type == "response.created" or evt_type == "response.in_progress":
            if not self.started:
                self.started = True
                self.response_id = (event.get("response") or {}).get("id", "")
                out.append(MessageStartEvent(
                    message=MessageResponse(
                        id=self.response_id,
                        type="message",
                        role="assistant",
                        content=[],
                        model=self.model,
                        usage=Usage(),
                    ),
                ))
            return out

        # A new output item starts (text message OR function call)
        if evt_type == "response.output_item.added":
            item = event.get("item") or {}
            output_index = event.get("output_index", -1)
            item_type = item.get("type", "")

            if item_type == "function_call":
                block_index = self.next_block_index
                self.next_block_index += 1
                self.output_index_to_block[output_index] = (block_index, "tool_use", item.get("name"))
                out.append(ContentBlockStartEvent(
                    index=block_index,
                    content_block=ToolUseOutputBlock(
                        id=item.get("call_id") or item.get("id", ""),
                        name=item.get("name", ""),
                        input={},
                    ),
                ))
            elif item_type == "message":
                # Will get text deltas next; allocate a block now
                block_index = self.next_block_index
                self.next_block_index += 1
                self.output_index_to_block[output_index] = (block_index, "text", None)
                out.append(ContentBlockStartEvent(
                    index=block_index,
                    content_block=TextOutputBlock(text=""),
                ))
            return out

        # Text delta inside a message
        if evt_type == "response.output_text.delta":
            output_index = event.get("output_index", -1)
            mapping = self.output_index_to_block.get(output_index)
            if mapping is None:
                return out
            block_index, _kind, _name = mapping
            delta_text = event.get("delta", "")
            if delta_text:
                out.append(ContentBlockDeltaEvent(
                    index=block_index,
                    delta=TextDelta(text=delta_text),
                ))
            return out

        # Function call argument delta
        if evt_type == "response.function_call_arguments.delta":
            output_index = event.get("output_index", -1)
            mapping = self.output_index_to_block.get(output_index)
            if mapping is None:
                return out
            block_index, _kind, _name = mapping
            delta_str = event.get("delta", "")
            if delta_str:
                out.append(ContentBlockDeltaEvent(
                    index=block_index,
                    delta=InputJsonDelta(partial_json=delta_str),
                ))
            return out

        # Output item complete
        if evt_type == "response.output_item.done":
            output_index = event.get("output_index", -1)
            mapping = self.output_index_to_block.get(output_index)
            if mapping is None:
                return out
            block_index, _kind, _name = mapping
            out.append(ContentBlockStopEvent(index=block_index))
            return out

        # Final completion
        if evt_type == "response.completed":
            response = event.get("response") or {}
            usage = response.get("usage") or {}
            self.accumulated_input_tokens = usage.get("input_tokens", 0)
            self.accumulated_output_tokens = usage.get("output_tokens", 0)
            self.cache_read_tokens = (usage.get("input_tokens_details") or {}).get("cached_tokens", 0)
            self.final_stop_reason = _map_stop_reason(response.get("status"))
            return out

        # Other events we don't care about: response.reasoning_summary.*, etc.
        return out

    def finish(self) -> list[StreamEvent]:
        """Emit final MessageDelta + MessageStop events."""
        out: list[StreamEvent] = []
        out.append(MessageDeltaEvent(
            delta=MessageDelta(
                stop_reason=self.final_stop_reason or "end_turn",
                stop_sequence=None,
            ),
            usage=Usage(
                input_tokens=self.accumulated_input_tokens,
                output_tokens=self.accumulated_output_tokens,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=self.cache_read_tokens,
            ),
        ))
        out.append(MessageStopEvent())
        return out


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _expect_success(response: httpx.Response) -> None:
    """Raise an ApiResponseError on non-2xx responses."""
    if 200 <= response.status_code < 300:
        return
    body = response.text
    error_type = None
    message = None
    try:
        data = json.loads(body)
        if "error" in data:
            err_obj = data["error"]
            error_type = err_obj.get("type")
            message = err_obj.get("message")
    except (json.JSONDecodeError, KeyError):
        pass

    retryable = response.status_code in (429, 500, 502, 503, 529)
    raise ApiResponseError(
        status=response.status_code,
        error_type=error_type,
        message=message,
        request_id_val=response.headers.get("x-request-id"),
        body=body,
        retryable=retryable,
    )


def _clone_request(req: MessageRequest, *, stream: bool) -> MessageRequest:
    return MessageRequest(
        model=req.model,
        max_tokens=req.max_tokens,
        messages=req.messages,
        system=req.system,
        tools=req.tools,
        tool_choice=req.tool_choice,
        stream=stream,
    )
