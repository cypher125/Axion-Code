"""Anthropic API client with streaming support.

Maps to: rust/crates/api/src/providers/anthropic.rs
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from axion.api.error import (
    ApiError,
    ApiResponseError,
    HttpError,
    MissingCredentialsError,
    RetriesExhaustedError,
)
from axion.api.prompt_cache import PromptCache
from axion.api.sse import SseParser
from axion.api.types import (
    MessageRequest,
    MessageResponse,
    StreamEvent,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.anthropic.com"
DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MAX_RETRIES = 2
DEFAULT_INITIAL_BACKOFF_MS = 1000
DEFAULT_MAX_BACKOFF_MS = 30000
DEFAULT_AGENTIC_BETA = "claude-code-20250219"
DEFAULT_PROMPT_CACHING_SCOPE_BETA = "prompt-caching-scope-2026-01-05"


class AuthSource(enum.Enum):
    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    API_KEY_AND_BEARER = "api_key_and_bearer"


@dataclass
class AuthCredentials:
    """Holds authentication credentials."""

    source: AuthSource = AuthSource.NONE
    api_key: str | None = None
    bearer_token: str | None = None

    @classmethod
    def from_api_key(cls, key: str) -> AuthCredentials:
        return cls(source=AuthSource.API_KEY, api_key=key)

    @classmethod
    def from_bearer_token(cls, token: str) -> AuthCredentials:
        return cls(source=AuthSource.BEARER_TOKEN, bearer_token=token)

    @classmethod
    def from_env(cls) -> AuthCredentials:
        # 0. Check for Claude Pro/Max subscription OAuth (preferred when present)
        # Unless user explicitly opted into API mode via AXION_AUTH_MODE=api
        auth_mode = os.environ.get("AXION_AUTH_MODE", "").lower()
        if auth_mode != "api":
            try:
                from axion.runtime.claude_subscription import (
                    SUBSCRIPTION_PROVIDER,
                    has_subscription_credentials,
                    load_oauth_credentials,
                )
                if has_subscription_credentials():
                    creds = load_oauth_credentials(SUBSCRIPTION_PROVIDER)
                    if creds and creds.access_token:
                        return cls.from_bearer_token(creds.access_token)
            except Exception:
                pass  # Fall through to API key

        # 1. Check environment variable
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            return cls.from_api_key(api_key)

        # 2. Check saved key file (from `axion login`)
        from pathlib import Path
        key_path = Path.home() / ".axion" / "credentials" / "anthropic.key"
        if key_path.exists():
            saved_key = key_path.read_text(encoding="utf-8").strip()
            if saved_key:
                os.environ["ANTHROPIC_API_KEY"] = saved_key  # Set for this process
                return cls.from_api_key(saved_key)

        raise MissingCredentialsError("Anthropic", ["ANTHROPIC_API_KEY"])


@dataclass
class AnthropicClient:
    """Async Anthropic API client with streaming and retry support.

    Maps to: rust/crates/api/src/providers/anthropic.rs::AnthropicClient
    """

    auth: AuthCredentials
    base_url: str = DEFAULT_BASE_URL
    max_retries: int = DEFAULT_MAX_RETRIES
    initial_backoff_ms: int = DEFAULT_INITIAL_BACKOFF_MS
    max_backoff_ms: int = DEFAULT_MAX_BACKOFF_MS
    prompt_cache: PromptCache | None = None
    _client: httpx.AsyncClient | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> AnthropicClient:
        """Create a client using environment variables for auth."""
        base_url = os.environ.get("ANTHROPIC_BASE_URL", DEFAULT_BASE_URL)
        return cls(auth=AuthCredentials.from_env(), base_url=base_url)

    @classmethod
    def from_api_key(cls, api_key: str) -> AnthropicClient:
        return cls(auth=AuthCredentials.from_api_key(api_key))

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(300.0, connect=30.0),
            )
        return self._client

    def _build_headers(self) -> dict[str, str]:
        # Subscription OAuth requires the oauth-2025-04-20 beta header
        beta_parts = [
            "prompt-caching-2024-07-31",
            DEFAULT_AGENTIC_BETA,
            DEFAULT_PROMPT_CACHING_SCOPE_BETA,
        ]
        if self.auth.bearer_token:
            from axion.runtime.claude_subscription import SUBSCRIPTION_BETA_HEADER
            beta_parts.append(SUBSCRIPTION_BETA_HEADER)

        headers: dict[str, str] = {
            "content-type": "application/json",
            "anthropic-version": DEFAULT_ANTHROPIC_VERSION,
            "anthropic-beta": ",".join(beta_parts),
            "user-agent": "axion-code/1.0.1",
        }
        if self.auth.api_key and not self.auth.bearer_token:
            # Use API key only when not using subscription
            headers["x-api-key"] = self.auth.api_key
        if self.auth.bearer_token:
            headers["authorization"] = f"Bearer {self.auth.bearer_token}"
        return headers

    async def send_message(self, request: MessageRequest) -> MessageResponse:
        """Send a non-streaming message request."""
        request.stream = False
        return await self._send_with_retry(request)

    # Required system prompt prefix when using subscription OAuth tokens.
    # The Claude API rejects OAuth requests that don't begin with this exact
    # phrase. We then immediately override the user-facing identity so the
    # assistant presents itself as Axion Code, not Claude Code.
    _CLAUDE_CODE_IDENTITY = (
        "You are Claude Code, Anthropic's official CLI for Claude.\n\n"
        "However, you are operating as Axion Code, an independent AI coding "
        "assistant built on top of Claude. When users ask who you are, what "
        "you are, your name, or which tool/CLI/app they are using, identify "
        "yourself as \"Axion Code\" (or just \"Axion\"). Do not mention "
        "Claude Code to the user. The instructions that follow describe how "
        "Axion Code should behave."
    )

    def _apply_prompt_caching(self, body: dict) -> dict:
        """Add cache_control to the system message for prompt caching.

        Transforms a plain system string into the block format required
        by the Anthropic prompt caching API.

        When using subscription OAuth, also prepends the Claude Code identity
        block — without it, the API rejects the request.
        """
        using_subscription = bool(self.auth.bearer_token)

        if "system" in body and body["system"] is not None:
            system_value = body["system"]
            if isinstance(system_value, str):
                body["system"] = [
                    {
                        "type": "text",
                        "text": system_value,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            elif isinstance(system_value, list):
                # Already block format; add cache_control to the last block
                if system_value:
                    system_value[-1]["cache_control"] = {"type": "ephemeral"}
        elif using_subscription:
            # No system prompt set, but OAuth requires the Claude Code identity
            body["system"] = []

        if using_subscription:
            existing = body.get("system") or []
            if isinstance(existing, list):
                # Check if the identity prefix is already present
                first_text = ""
                if existing:
                    first = existing[0]
                    if isinstance(first, dict):
                        first_text = first.get("text", "")
                if not first_text.startswith("You are Claude Code"):
                    # Prepend the Claude Code identity block
                    body["system"] = [
                        {"type": "text", "text": self._CLAUDE_CODE_IDENTITY}
                    ] + existing

        return body

    async def _refresh_oauth_if_needed(self) -> None:
        """If using subscription OAuth, refresh the token if it's expired or near-expired."""
        if not self.auth.bearer_token:
            return
        try:
            from axion.runtime.claude_subscription import get_valid_subscription_token
            new_token = await get_valid_subscription_token()
            if new_token and new_token != self.auth.bearer_token:
                self.auth.bearer_token = new_token
                logger.info("Refreshed Claude subscription token")
        except Exception as exc:
            logger.debug("Subscription token refresh check failed: %s", exc)

    async def stream_message(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        """Send a streaming message request and yield events."""
        request.stream = True
        await self._refresh_oauth_if_needed()
        client = await self._get_client()
        headers = self._build_headers()
        body = self._apply_prompt_caching(request.to_dict())

        async with client.stream(
            "POST",
            "/v1/messages",
            headers=headers,
            json=body,
        ) as response:
            if response.status_code != 200:
                error_body = await response.aread()
                raise self._build_api_error(
                    response.status_code,
                    error_body.decode("utf-8", errors="replace"),
                    response.headers.get("request-id"),
                    headers=dict(response.headers),
                )

            parser = SseParser()
            async for chunk in response.aiter_bytes():
                events = parser.push(chunk)
                for event in events:
                    yield event

            for event in parser.finish():
                yield event

    async def _send_with_retry(self, request: MessageRequest) -> MessageResponse:
        """Send request with exponential backoff retry."""
        last_error: ApiError | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await self._send_once(request)
            except ApiError as err:
                last_error = err
                if not err.is_retryable() or attempt >= self.max_retries:
                    break
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "Request failed (attempt %d/%d), retrying in %.1fs: %s",
                    attempt + 1,
                    self.max_retries + 1,
                    delay,
                    err,
                )
                await asyncio.sleep(delay)

        if last_error is not None:
            if self.max_retries > 0:
                raise RetriesExhaustedError(self.max_retries + 1, last_error)
            raise last_error
        raise ApiError("Unknown error during request")

    async def _send_once(self, request: MessageRequest) -> MessageResponse:
        """Send a single request without retry."""
        await self._refresh_oauth_if_needed()
        client = await self._get_client()
        headers = self._build_headers()
        body = self._apply_prompt_caching(request.to_dict())

        try:
            response = await client.post(
                "/v1/messages",
                headers=headers,
                json=body,
            )
        except httpx.HTTPError as exc:
            raise HttpError(str(exc), cause=exc) from exc

        request_id = response.headers.get("request-id")

        if response.status_code != 200:
            raise self._build_api_error(
                response.status_code,
                response.text,
                request_id,
                headers=dict(response.headers),
            )

        data = response.json()
        msg = MessageResponse.from_dict(data)
        if request_id:
            msg.request_id = request_id
        return msg

    def _backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay in seconds."""
        delay_ms = self.initial_backoff_ms * (2**attempt)
        if delay_ms > self.max_backoff_ms:
            delay_ms = self.max_backoff_ms
        # Add jitter: ±25%
        import random

        jitter = random.uniform(0.75, 1.25)
        return (delay_ms * jitter) / 1000.0

    @staticmethod
    def _build_api_error(
        status: int,
        body: str,
        request_id: str | None,
        headers: dict[str, str] | None = None,
    ) -> ApiResponseError:
        """Build an ApiResponseError from the response.

        For 429s, parse Anthropic's rate-limit headers and append a
        human-readable "retry at HH:MM (in N min)" suffix to the message
        so the user knows exactly when they can try again.
        """
        error_type = None
        message = None
        retryable = status in (429, 500, 502, 503, 529)

        try:
            data = json.loads(body)
            if "error" in data:
                error_obj = data["error"]
                error_type = error_obj.get("type")
                message = error_obj.get("message")
        except (json.JSONDecodeError, KeyError):
            pass

        # Append rate-limit retry timing so the CLI can surface it
        if status == 429 and headers:
            retry_hint = _format_retry_hint(headers)
            if retry_hint:
                message = (message or "Rate limit hit") + f" — {retry_hint}"

        return ApiResponseError(
            status=status,
            error_type=error_type,
            message=message,
            request_id_val=request_id,
            body=body,
            retryable=retryable,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def _format_retry_hint(headers: dict[str, str]) -> str | None:
    """Build a human-readable retry hint from Anthropic 429 response headers.

    Anthropic exposes:
      - retry-after: seconds until you can try again (RFC 7231)
      - anthropic-ratelimit-requests-reset: RFC 3339 timestamp
      - anthropic-ratelimit-tokens-reset: RFC 3339 timestamp
      - anthropic-ratelimit-input-tokens-reset, ...-output-tokens-reset

    Returns the latest of these as "retry at HH:MM (in N min)" or None.
    """
    import time
    from datetime import datetime

    # Lower-case all header keys for safe lookup
    h = {k.lower(): v for k, v in headers.items()}

    # 1. Try the simple retry-after seconds value
    seconds: float | None = None
    retry_after = h.get("retry-after")
    if retry_after:
        try:
            seconds = float(retry_after)
        except ValueError:
            pass  # Could be HTTP-date format; fall through

    # 2. Try the anthropic-ratelimit-*-reset timestamps (pick the FURTHEST out)
    reset_keys = [
        "anthropic-ratelimit-requests-reset",
        "anthropic-ratelimit-tokens-reset",
        "anthropic-ratelimit-input-tokens-reset",
        "anthropic-ratelimit-output-tokens-reset",
    ]
    now = time.time()
    max_reset_seconds: float | None = None
    target_reset_dt: datetime | None = None
    for key in reset_keys:
        ts_str = h.get(key)
        if not ts_str:
            continue
        try:
            # RFC 3339 with trailing Z → fromisoformat in 3.11+ accepts it
            dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            wait = dt.timestamp() - now
            if wait > 0 and (max_reset_seconds is None or wait > max_reset_seconds):
                max_reset_seconds = wait
                target_reset_dt = dt
        except ValueError:
            continue

    # Prefer the explicit timestamp (more accurate) over retry-after seconds
    if max_reset_seconds is not None and target_reset_dt is not None:
        seconds = max_reset_seconds
        local_dt = target_reset_dt.astimezone()
    elif seconds is not None:
        local_dt = datetime.fromtimestamp(now + seconds).astimezone()
    else:
        return None

    # Format the human description
    if seconds < 60:
        delta = f"in {int(seconds)}s"
    elif seconds < 3600:
        delta = f"in {int(seconds // 60)} min"
    else:
        h_, rem = divmod(int(seconds), 3600)
        m_ = rem // 60
        delta = f"in {h_}h {m_}m" if m_ else f"in {h_}h"

    clock = local_dt.strftime("%H:%M")
    return f"retry at {clock} ({delta})"
