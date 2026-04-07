"""Mock Anthropic API server for parity testing.

Maps to: rust/crates/mock-anthropic-service/src/lib.rs
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from tests.mock_anthropic.scenarios import (
    build_scenario_response,
    detect_scenario,
    streaming_text_sse,
    text_message_response,
)

logger = logging.getLogger(__name__)


@dataclass
class CapturedRequest:
    """Captured HTTP request metadata."""

    method: str
    path: str
    headers: dict[str, str]
    scenario: str = ""
    stream: bool = False
    raw_body: str = ""
    attempt: int = 1


class MockAnthropicService:
    """Async mock Anthropic API server for testing.

    Maps to: rust/crates/mock-anthropic-service/src/lib.rs::MockAnthropicService

    Spawns on a random port. Captures all requests for inspection.
    Routes to scenario-specific responses based on PARITY_SCENARIO: prefix.
    """

    def __init__(self) -> None:
        self._app = web.Application()
        self._app.router.add_post("/v1/messages", self._handle_messages)
        self._app.router.add_post("/v1/messages/count_tokens", self._handle_count_tokens)
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._requests: list[CapturedRequest] = []
        self._host = "127.0.0.1"
        self._port = 0

    @classmethod
    async def spawn(cls) -> MockAnthropicService:
        """Create and start the mock server on a random port."""
        service = cls()
        service._runner = web.AppRunner(service._app)
        await service._runner.setup()
        service._site = web.TCPSite(service._runner, service._host, 0)
        await service._site.start()

        # Get the actual port
        sockets = service._site._server.sockets  # type: ignore[attr-defined]
        if sockets:
            service._port = sockets[0].getsockname()[1]

        logger.info("Mock Anthropic service started on port %d", service._port)
        return service

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    @property
    def captured_requests(self) -> list[CapturedRequest]:
        return list(self._requests)

    async def shutdown(self) -> None:
        """Stop the mock server."""
        if self._runner:
            await self._runner.cleanup()

    async def _handle_messages(self, request: web.Request) -> web.StreamResponse:
        """Handle POST /v1/messages."""
        body = await request.text()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            return web.Response(status=400, text="Invalid JSON")

        is_stream = data.get("stream", False)
        messages = data.get("messages", [])
        scenario = detect_scenario(messages)

        # Capture request
        self._requests.append(CapturedRequest(
            method="POST",
            path="/v1/messages",
            headers=dict(request.headers),
            scenario=scenario.value if scenario else "",
            stream=is_stream,
            raw_body=body,
            attempt=len(self._requests) + 1,
        ))

        # Build response
        if scenario:
            response_data = build_scenario_response(scenario, data, is_stream)
        else:
            if is_stream:
                response_data = streaming_text_sse()
            else:
                response_data = text_message_response()

        if is_stream:
            # SSE streaming response
            assert isinstance(response_data, str)
            resp = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "request-id": f"req_mock_{len(self._requests)}",
                },
            )
            await resp.prepare(request)
            await resp.write(response_data.encode("utf-8"))
            await resp.write_eof()
            return resp
        else:
            # Non-streaming JSON response
            assert isinstance(response_data, dict)
            return web.json_response(
                response_data,
                headers={"request-id": f"req_mock_{len(self._requests)}"},
            )

    async def _handle_count_tokens(self, request: web.Request) -> web.Response:
        """Handle POST /v1/messages/count_tokens."""
        return web.json_response({"input_tokens": 42})


# ---------------------------------------------------------------------------
# Convenience context manager
# ---------------------------------------------------------------------------

class mock_anthropic_server:
    """Async context manager for the mock server.

    Usage:
        async with mock_anthropic_server() as service:
            client = AnthropicClient(base_url=service.base_url, ...)
    """

    def __init__(self) -> None:
        self._service: MockAnthropicService | None = None

    async def __aenter__(self) -> MockAnthropicService:
        self._service = await MockAnthropicService.spawn()
        return self._service

    async def __aexit__(self, *args: Any) -> None:
        if self._service:
            await self._service.shutdown()
