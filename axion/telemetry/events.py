"""Telemetry event types.

Maps to: rust/crates/telemetry/src/lib.rs (event types)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AnalyticsEvent:
    """User action event."""

    namespace: str
    action: str
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class HttpRequestStarted:
    session_id: str
    attempt: int
    method: str
    path: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class HttpRequestSucceeded:
    session_id: str
    attempt: int
    method: str
    path: str
    status: int
    request_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class HttpRequestFailed:
    session_id: str
    attempt: int
    method: str
    path: str
    error: str
    retryable: bool = False
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionTraceRecord:
    session_id: str
    sequence: int
    name: str
    timestamp_ms: int
    attributes: dict[str, Any] = field(default_factory=dict)


TelemetryEvent = (
    HttpRequestStarted
    | HttpRequestSucceeded
    | HttpRequestFailed
    | AnalyticsEvent
    | SessionTraceRecord
)
