"""Bootstrap phases for CLI startup.

Maps to: rust/crates/runtime/src/bootstrap.rs
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class BootstrapPhase(enum.Enum):
    VERSION_CHECK = "version_check"
    PROFILER = "profiler"
    SYSTEM_PROMPT = "system_prompt"
    DAEMON = "daemon"
    AUTH = "auth"
    CONFIG = "config"
    PLUGINS = "plugins"
    MCP = "mcp"
    READY = "ready"


@dataclass
class BootstrapPlan:
    """Ordered list of bootstrap phases to execute."""

    phases: list[BootstrapPhase] = field(default_factory=lambda: [
        BootstrapPhase.VERSION_CHECK,
        BootstrapPhase.CONFIG,
        BootstrapPhase.AUTH,
        BootstrapPhase.PLUGINS,
        BootstrapPhase.MCP,
        BootstrapPhase.SYSTEM_PROMPT,
        BootstrapPhase.READY,
    ])

    def includes(self, phase: BootstrapPhase) -> bool:
        return phase in self.phases
