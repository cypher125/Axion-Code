"""MCP tool registry bridge.

Maps to: rust/crates/runtime/src/mcp_tool_bridge.rs
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class McpConnectionStatus(enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    AUTH_REQUIRED = "auth_required"
    ERROR = "error"


@dataclass
class McpToolInfo:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpResourceInfo:
    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None


@dataclass
class McpServerState:
    """State of a connected MCP server."""

    server_name: str
    status: McpConnectionStatus = McpConnectionStatus.DISCONNECTED
    tools: list[McpToolInfo] = field(default_factory=list)
    resources: list[McpResourceInfo] = field(default_factory=list)
    error_message: str | None = None


class McpToolRegistry:
    """Tracks connected MCP servers and their available tools.

    Maps to: rust/crates/runtime/src/mcp_tool_bridge.rs::McpToolRegistry
    """

    def __init__(self) -> None:
        self._servers: dict[str, McpServerState] = {}

    def register_server(self, state: McpServerState) -> None:
        self._servers[state.server_name] = state

    def get_server(self, name: str) -> McpServerState | None:
        return self._servers.get(name)

    def all_servers(self) -> list[McpServerState]:
        return list(self._servers.values())

    def all_tools(self) -> list[tuple[str, McpToolInfo]]:
        """Get all tools with their server name."""
        tools = []
        for state in self._servers.values():
            if state.status == McpConnectionStatus.CONNECTED:
                for tool in state.tools:
                    tools.append((state.server_name, tool))
        return tools

    def find_tool(self, tool_name: str) -> tuple[str, McpToolInfo] | None:
        """Find a tool by name across all servers."""
        for server_name, tool in self.all_tools():
            if tool.name == tool_name:
                return (server_name, tool)
        return None
