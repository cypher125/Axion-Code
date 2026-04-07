"""Remote session support.

Maps to: rust/crates/runtime/src/remote.rs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RemoteSessionContext:
    """Context for a remote session connection."""

    session_id: str
    host: str
    port: int = 0
    protocol: str = "https"
    auth_token: str | None = None


@dataclass
class UpstreamProxy:
    """Proxy configuration for upstream connections."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout_ms: int = 30_000
