"""Session-level event tracer.

Maps to: rust/crates/telemetry/src/lib.rs (SessionTracer)
"""

from __future__ import annotations

import threading
import time
from typing import Any

from axion.telemetry.events import (
    AnalyticsEvent,
    HttpRequestFailed,
    HttpRequestStarted,
    HttpRequestSucceeded,
    SessionTraceRecord,
)
from axion.telemetry.sink import TelemetrySink


class SessionTracer:
    """Session-level event recorder with atomic sequence counter.

    Maps to: rust/crates/telemetry/src/lib.rs::SessionTracer
    """

    def __init__(self, session_id: str, sink: TelemetrySink) -> None:
        self.session_id = session_id
        self._sink = sink
        self._sequence = 0
        self._lock = threading.Lock()

    def _next_seq(self) -> int:
        with self._lock:
            self._sequence += 1
            return self._sequence

    def record(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Record a session trace event."""
        event = SessionTraceRecord(
            session_id=self.session_id,
            sequence=self._next_seq(),
            name=name,
            timestamp_ms=int(time.time() * 1000),
            attributes=attributes or {},
        )
        self._sink.record(event)

    def record_http_request_started(
        self, attempt: int, method: str, path: str
    ) -> None:
        self._sink.record(HttpRequestStarted(
            session_id=self.session_id,
            attempt=attempt,
            method=method,
            path=path,
        ))

    def record_http_request_succeeded(
        self,
        attempt: int,
        method: str,
        path: str,
        status: int,
        request_id: str | None = None,
    ) -> None:
        self._sink.record(HttpRequestSucceeded(
            session_id=self.session_id,
            attempt=attempt,
            method=method,
            path=path,
            status=status,
            request_id=request_id,
        ))

    def record_http_request_failed(
        self,
        attempt: int,
        method: str,
        path: str,
        error: str,
        retryable: bool = False,
    ) -> None:
        self._sink.record(HttpRequestFailed(
            session_id=self.session_id,
            attempt=attempt,
            method=method,
            path=path,
            error=error,
            retryable=retryable,
        ))

    def record_analytics(self, event: AnalyticsEvent) -> None:
        self._sink.record(event)
