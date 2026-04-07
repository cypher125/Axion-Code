"""Anthropic API client with streaming support.

Maps to: rust/crates/api/src/providers/anthropic.rs
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

import httpx

from axion.api.error import (
    ApiError,
    ApiResponseError,
    AuthError,
    BackoffOverflowError,
    ExpiredOAuthTokenError,
    HttpError,
    MissingCredentialsError,
    RetriesExhaustedError,
    looks_like_context_window_error,
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
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            return cls.from_api_key(api_key)
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
        headers: dict[str, str] = {
            "content-type": "application/json",
            "anthropic-version": DEFAULT_ANTHROPIC_VERSION,
            "anthropic-beta": f"prompt-caching-2024-07-31,{DEFAULT_AGENTIC_BETA},{DEFAULT_PROMPT_CACHING_SCOPE_BETA}",
            "user-agent": "axion-code/0.1.0",
        }
        if self.auth.api_key:
            headers["x-api-key"] = self.auth.api_key
        if self.auth.bearer_token:
            headers["authorization"] = f"Bearer {self.auth.bearer_token}"
        return headers

    async def send_message(self, request: MessageRequest) -> MessageResponse:
        """Send a non-streaming message request."""
        request.stream = False
        return await self._send_with_retry(request)

    @staticmethod
    def _apply_prompt_caching(body: dict) -> dict:
        """Add cache_control to the system message for prompt caching.

        Transforms a plain system string into the block format required
        by the Anthropic prompt caching API.
        """
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
        return body

    async def stream_message(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        """Send a streaming message request and yield events."""
        request.stream = True
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
                response.status_code, response.text, request_id
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
        status: int, body: str, request_id: str | None
    ) -> ApiResponseError:
        """Build an ApiResponseError from the response."""
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
