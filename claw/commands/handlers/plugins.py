"""Plugin slash command handler.

Maps to: rust/crates/commands/src/lib.rs (handle_plugins_slash_command)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from claw.plugins.manager import PluginManager


def handle_plugins_command(args: str, manager: PluginManager) -> str:
    """Handle /plugins [list|install|enable|disable|uninstall] commands."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else ""

    if action == "list":
        summaries = manager.registry.summaries()
        if not summaries:
            return "No plugins installed."
        lines = ["Installed plugins:", ""]
        for s in summaries:
            status = "enabled" if s.enabled else "disabled"
            lines.append(
                f"  {s.name} v{s.version} [{status}] "
                f"— {s.description} ({s.tool_count} tools, {s.command_count} commands)"
            )
        return "\n".join(lines)

    if action == "install":
        if not target:
            return "Usage: /plugins install <path>"
        summary = manager.install(Path(target))
        if summary:
            return f"Installed plugin: {summary.name} v{summary.version}"
        return f"Failed to install plugin from: {target}"

    if action == "enable":
        if manager.enable(target):
            return f"Enabled plugin: {target}"
        return f"Plugin not found: {target}"

    if action == "disable":
        if manager.disable(target):
            return f"Disabled plugin: {target}"
        return f"Plugin not found: {target}"

    if action == "uninstall":
        if manager.uninstall(target):
            return f"Uninstalled plugin: {target}"
        return f"Plugin not found: {target}"

    return f"Unknown plugin action: {action}. Use: list, install, enable, disable, uninstall"
