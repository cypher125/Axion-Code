"""Telemetry sinks for event recording.

Maps to: rust/crates/telemetry/src/lib.rs (TelemetrySink)
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from axion.telemetry.events import TelemetryEvent


@runtime_checkable
class TelemetrySink(Protocol):
    """Protocol for recording telemetry events."""

    def record(self, event: TelemetryEvent) -> None: ...


class MemoryTelemetrySink:
    """In-memory telemetry sink for testing."""

    def __init__(self) -> None:
        self._events: list[TelemetryEvent] = []
        self._lock = threading.Lock()

    def record(self, event: TelemetryEvent) -> None:
        with self._lock:
            self._events.append(event)

    def events(self) -> list[TelemetryEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


class JsonlTelemetrySink:
    """JSONL file-based telemetry sink."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: TelemetryEvent) -> None:
        with self._lock:
            with open(self._path, "a", encoding="utf-8") as f:
                # Simple serialization
                data: dict[str, Any] = {
                    "type": type(event).__name__,
                }
                for k, v in vars(event).items():
                    data[k] = v
                f.write(json.dumps(data, default=str) + "\n")
