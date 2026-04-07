"""Permission system for tool execution.

Maps to: rust/crates/runtime/src/permissions.rs
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


class PermissionMode(enum.Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"
    PROMPT = "prompt"
    ALLOW = "allow"


# ---------------------------------------------------------------------------
# Permission outcomes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PermissionAllow:
    """Tool execution is allowed."""
    pass


@dataclass(frozen=True)
class PermissionDeny:
    """Tool execution is denied."""
    reason: str


PermissionOutcome = PermissionAllow | PermissionDeny


# ---------------------------------------------------------------------------
# Permission request / context
# ---------------------------------------------------------------------------

@dataclass
class PermissionRequest:
    tool_name: str
    input_json: str
    current_mode: PermissionMode
    required_mode: PermissionMode
    reason: str = ""


@dataclass
class PermissionContext:
    override_decision: PermissionOverride | None = None
    override_reason: str | None = None


class PermissionOverride(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"


# ---------------------------------------------------------------------------
# Permission prompter protocol
# ---------------------------------------------------------------------------

class PermissionPromptDecision(enum.Enum):
    ALLOW = "allow"
    DENY = "deny"


@runtime_checkable
class PermissionPrompter(Protocol):
    """Interactive permission decision protocol."""

    async def decide(self, request: PermissionRequest) -> PermissionPromptDecision: ...


# ---------------------------------------------------------------------------
# Tool permission requirements
# ---------------------------------------------------------------------------

# Tools and their minimum required permission mode
TOOL_PERMISSION_REQUIREMENTS: dict[str, PermissionMode] = {
    "Bash": PermissionMode.WORKSPACE_WRITE,
    "Write": PermissionMode.WORKSPACE_WRITE,
    "Edit": PermissionMode.WORKSPACE_WRITE,
    "NotebookEdit": PermissionMode.WORKSPACE_WRITE,
    "Read": PermissionMode.READ_ONLY,
    "Glob": PermissionMode.READ_ONLY,
    "Grep": PermissionMode.READ_ONLY,
    "WebSearch": PermissionMode.READ_ONLY,
    "WebFetch": PermissionMode.READ_ONLY,
    "Agent": PermissionMode.READ_ONLY,
    "TodoWrite": PermissionMode.READ_ONLY,
}


# ---------------------------------------------------------------------------
# Permission policy
# ---------------------------------------------------------------------------

@dataclass
class PermissionPolicy:
    """Evaluates whether tool execution is allowed.

    Maps to: rust/crates/runtime/src/permissions.rs::PermissionPolicy
    """

    mode: PermissionMode = PermissionMode.ALLOW
    allow_rules: list[str] = field(default_factory=list)
    deny_rules: list[str] = field(default_factory=list)

    def authorize(
        self,
        tool_name: str,
        input_json: str = "",
        prompter: PermissionPrompter | None = None,
    ) -> PermissionOutcome:
        """Check if a tool invocation is allowed under current policy."""
        # Explicit deny rules
        for rule in self.deny_rules:
            if self._matches_rule(rule, tool_name):
                return PermissionDeny(reason=f"Denied by rule: {rule}")

        # Explicit allow rules
        for rule in self.allow_rules:
            if self._matches_rule(rule, tool_name):
                return PermissionAllow()

        # Mode-based check
        if self.mode == PermissionMode.ALLOW:
            return PermissionAllow()

        if self.mode == PermissionMode.DANGER_FULL_ACCESS:
            return PermissionAllow()

        required = TOOL_PERMISSION_REQUIREMENTS.get(tool_name, PermissionMode.WORKSPACE_WRITE)

        if self.mode == PermissionMode.READ_ONLY:
            if required == PermissionMode.READ_ONLY:
                return PermissionAllow()
            return PermissionDeny(
                reason=f"Tool '{tool_name}' requires {required.value}, "
                f"but current mode is {self.mode.value}"
            )

        if self.mode == PermissionMode.WORKSPACE_WRITE:
            if required in (PermissionMode.READ_ONLY, PermissionMode.WORKSPACE_WRITE):
                return PermissionAllow()
            return PermissionDeny(
                reason=f"Tool '{tool_name}' requires {required.value}"
            )

        # PROMPT mode — would need interactive approval
        return PermissionAllow()

    @staticmethod
    def _matches_rule(rule: str, tool_name: str) -> bool:
        """Check if a rule pattern matches a tool name."""
        if rule == "*":
            return True
        if rule == tool_name:
            return True
        if rule.endswith("*") and tool_name.startswith(rule[:-1]):
            return True
        return False
