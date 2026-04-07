"""MCP transport configuration types.

Maps to: rust/crates/runtime/src/mcp_client.rs
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class McpTransportType(enum.Enum):
    STDIO = "stdio"
    SSE = "sse"
    HTTP = "http"
    WEBSOCKET = "websocket"
    SDK = "sdk"
    MANAGED_PROXY = "managed_proxy"


@dataclass
class McpStdioTransport:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    tool_call_timeout_ms: int | None = None


@dataclass
class McpRemoteTransport:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    auth: McpClientAuth | None = None


@dataclass
class McpSdkTransport:
    name: str


@dataclass
class McpManagedProxyTransport:
    url: str
    id: str


# Union type for all transport configurations
McpClientTransport = (
    McpStdioTransport
    | McpRemoteTransport
    | McpSdkTransport
    | McpManagedProxyTransport
)


class McpClientAuthType(enum.Enum):
    NONE = "none"
    OAUTH = "oauth"


@dataclass
class McpClientAuth:
    auth_type: McpClientAuthType = McpClientAuthType.NONE
    oauth_config: dict[str, Any] | None = None


@dataclass
class McpClientBootstrap:
    """Bootstrap configuration for an MCP client connection."""

    server_name: str
    normalized_name: str
    tool_prefix: str
    transport: McpClientTransport
    signature: str = ""
