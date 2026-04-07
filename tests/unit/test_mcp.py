"""Tests for MCP tool bridge and lifecycle."""

from claw.runtime.mcp.tool_bridge import (
    McpConnectionStatus,
    McpServerState,
    McpToolInfo,
    McpToolRegistry,
)
from claw.runtime.mcp.lifecycle import McpLifecycleManager


def test_mcp_registry_empty():
    reg = McpToolRegistry()
    assert reg.all_servers() == []
    assert reg.all_tools() == []


def test_mcp_registry_register_server():
    reg = McpToolRegistry()
    state = McpServerState(
        server_name="test-server",
        status=McpConnectionStatus.CONNECTED,
        tools=[
            McpToolInfo(name="tool1", description="First tool"),
            McpToolInfo(name="tool2", description="Second tool"),
        ],
    )
    reg.register_server(state)

    assert len(reg.all_servers()) == 1
    assert len(reg.all_tools()) == 2
    assert reg.get_server("test-server") is state


def test_mcp_find_tool():
    reg = McpToolRegistry()
    reg.register_server(McpServerState(
        server_name="srv",
        status=McpConnectionStatus.CONNECTED,
        tools=[McpToolInfo(name="my_tool")],
    ))

    result = reg.find_tool("my_tool")
    assert result is not None
    server_name, tool = result
    assert server_name == "srv"
    assert tool.name == "my_tool"

    assert reg.find_tool("nonexistent") is None


def test_mcp_disconnected_tools_hidden():
    reg = McpToolRegistry()
    reg.register_server(McpServerState(
        server_name="offline",
        status=McpConnectionStatus.DISCONNECTED,
        tools=[McpToolInfo(name="hidden_tool")],
    ))
    # Disconnected server tools should not appear
    assert reg.all_tools() == []


def test_lifecycle_manager_connected():
    manager = McpLifecycleManager()
    manager.mark_server_connected("srv1", [
        {"name": "tool_a", "description": "A"},
    ])

    state = manager.registry.get_server("srv1")
    assert state is not None
    assert state.status == McpConnectionStatus.CONNECTED
    assert len(state.tools) == 1


def test_lifecycle_manager_error():
    manager = McpLifecycleManager()
    manager.mark_server_error("srv2", "Connection refused")

    state = manager.registry.get_server("srv2")
    assert state is not None
    assert state.status == McpConnectionStatus.ERROR
    assert state.error_message == "Connection refused"
