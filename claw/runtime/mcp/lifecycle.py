"""Hardened MCP lifecycle management.

Maps to: rust/crates/runtime/src/mcp_lifecycle_hardened.rs
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from claw.runtime.mcp.tool_bridge import McpConnectionStatus, McpServerState, McpToolRegistry

logger = logging.getLogger(__name__)


@dataclass
class McpLifecycleEvent:
    server_name: str
    event_type: str
    message: str = ""
    error: str | None = None


class McpLifecycleManager:
    """Manages MCP server lifecycle with error handling and degradation.

    Maps to: rust/crates/runtime/src/mcp_lifecycle_hardened.rs
    """

    def __init__(self, registry: McpToolRegistry | None = None) -> None:
        self.registry = registry or McpToolRegistry()
        self._events: list[McpLifecycleEvent] = []

    def record_event(self, event: McpLifecycleEvent) -> None:
        self._events.append(event)
        if event.error:
            logger.warning(
                "MCP lifecycle event [%s] %s: %s",
                event.server_name,
                event.event_type,
                event.error,
            )

    def mark_server_connected(
        self, server_name: str, tools: list[Any] | None = None
    ) -> None:
        from claw.runtime.mcp.tool_bridge import McpToolInfo

        tool_infos = []
        if tools:
            for t in tools:
                if isinstance(t, McpToolInfo):
                    tool_infos.append(t)
                elif isinstance(t, dict):
                    tool_infos.append(McpToolInfo(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema", {}),
                    ))

        state = McpServerState(
            server_name=server_name,
            status=McpConnectionStatus.CONNECTED,
            tools=tool_infos,
        )
        self.registry.register_server(state)
        self.record_event(McpLifecycleEvent(
            server_name=server_name,
            event_type="connected",
            message=f"Connected with {len(tool_infos)} tools",
        ))

    def mark_server_error(self, server_name: str, error: str) -> None:
        state = McpServerState(
            server_name=server_name,
            status=McpConnectionStatus.ERROR,
            error_message=error,
        )
        self.registry.register_server(state)
        self.record_event(McpLifecycleEvent(
            server_name=server_name,
            event_type="error",
            error=error,
        ))

    def mark_server_disconnected(self, server_name: str) -> None:
        state = McpServerState(
            server_name=server_name,
            status=McpConnectionStatus.DISCONNECTED,
        )
        self.registry.register_server(state)
        self.record_event(McpLifecycleEvent(
            server_name=server_name,
            event_type="disconnected",
        ))
