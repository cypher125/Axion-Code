"""Plugin-level hook execution.

Maps to: rust/crates/plugins/src/hooks.rs
"""

from __future__ import annotations

from axion.runtime.hooks import HookConfig, HookRunner
from axion.plugins.manager import PluginRegistry


def hook_runner_from_registry(registry: PluginRegistry) -> HookRunner:
    """Create a HookRunner from aggregated plugin hooks."""
    hooks = registry.aggregated_hooks()

    return HookRunner(
        pre_tool_use=[HookConfig(command=cmd) for cmd in hooks["pre_tool_use"]],
        post_tool_use=[HookConfig(command=cmd) for cmd in hooks["post_tool_use"]],
        post_tool_use_failure=[
            HookConfig(command=cmd) for cmd in hooks["post_tool_use_failure"]
        ],
    )
