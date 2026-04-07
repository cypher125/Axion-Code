"""MCP slash command handler.

Maps to: rust/crates/commands/src/lib.rs (handle_mcp_slash_command)
"""

from __future__ import annotations

from typing import Any

from axion.runtime.mcp.tool_bridge import McpToolRegistry


def handle_mcp_command(args: str, registry: McpToolRegistry | None = None) -> str:
    """Handle /mcp [list|show <server>|help] commands."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else ""

    reg = registry or McpToolRegistry()

    if action in ("list", ""):
        servers = reg.all_servers()
        if not servers:
            return "No MCP servers connected."
        lines = ["Connected MCP servers:", ""]
        for server in servers:
            tool_count = len(server.tools)
            lines.append(
                f"  {server.server_name} [{server.status.value}] "
                f"— {tool_count} tool(s)"
            )
            if server.error_message:
                lines.append(f"    Error: {server.error_message}")
        return "\n".join(lines)

    if action == "show":
        if not target:
            return "Usage: /mcp show <server_name>"
        server = reg.get_server(target)
        if server is None:
            return f"Server not found: {target}"
        lines = [f"MCP Server: {server.server_name}", f"Status: {server.status.value}"]
        if server.tools:
            lines.append(f"\nTools ({len(server.tools)}):")
            for tool in server.tools:
                lines.append(f"  {tool.name} — {tool.description}")
        if server.resources:
            lines.append(f"\nResources ({len(server.resources)}):")
            for res in server.resources:
                lines.append(f"  {res.name} ({res.uri})")
        return "\n".join(lines)

    if action == "help":
        return (
            "MCP (Model Context Protocol) commands:\n"
            "  /mcp list          — List connected servers\n"
            "  /mcp show <name>   — Show server details and tools\n"
            "  /mcp help          — Show this help"
        )

    return f"Unknown MCP action: {action}. Use: list, show, help"
