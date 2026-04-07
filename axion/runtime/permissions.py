"""Permission system for tool execution.

Maps to: rust/crates/runtime/src/permissions.rs
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


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

class PermissionDecisionKind(enum.Enum):
    """Distinguishes one-time vs persistent permission decisions."""
    ALLOW_ONCE = "allow_once"
    ALLOW_ALWAYS = "allow_always"
    DENY = "deny"


@dataclass
class PermissionPolicy:
    """Evaluates whether tool execution is allowed.

    Maps to: rust/crates/runtime/src/permissions.rs::PermissionPolicy
    """

    mode: PermissionMode = PermissionMode.ALLOW
    allow_rules: list[str] = field(default_factory=list)
    deny_rules: list[str] = field(default_factory=list)
    _decision_cache: dict[str, PermissionOutcome] = field(
        default_factory=dict, repr=False
    )

    def remember_decision(
        self,
        tool_name: str,
        outcome: PermissionOutcome,
        *,
        kind: PermissionDecisionKind = PermissionDecisionKind.ALLOW_ALWAYS,
    ) -> None:
        """Cache a permission decision for a tool.

        Only ``ALLOW_ALWAYS`` decisions are cached; ``ALLOW_ONCE`` is not
        stored (it applies only to the current invocation).
        """
        if kind == PermissionDecisionKind.ALLOW_ONCE:
            return
        key = f"{tool_name}:{self.mode.value}"
        self._decision_cache[key] = outcome

    def persist_decisions(self, path: Path) -> None:
        """Save cached decisions to a JSON file."""
        serializable: dict[str, dict[str, str]] = {}
        for key, outcome in self._decision_cache.items():
            if isinstance(outcome, PermissionAllow):
                serializable[key] = {"outcome": "allow"}
            elif isinstance(outcome, PermissionDeny):
                serializable[key] = {"outcome": "deny", "reason": outcome.reason}

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
        logger.debug("Persisted %d permission decisions to %s", len(serializable), path)

    def load_decisions(self, path: Path) -> None:
        """Load cached decisions from a JSON file."""
        if not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load permission decisions from %s: %s", path, exc)
            return

        for key, value in data.items():
            outcome_str = value.get("outcome", "")
            if outcome_str == "allow":
                self._decision_cache[key] = PermissionAllow()
            elif outcome_str == "deny":
                self._decision_cache[key] = PermissionDeny(
                    reason=value.get("reason", "persisted deny")
                )

        logger.debug("Loaded %d permission decisions from %s", len(self._decision_cache), path)

    def authorize(
        self,
        tool_name: str,
        input_json: str = "",
        prompter: PermissionPrompter | None = None,
    ) -> PermissionOutcome:
        """Check if a tool invocation is allowed under current policy."""
        # Check decision cache first
        cache_key = f"{tool_name}:{self.mode.value}"
        if cache_key in self._decision_cache:
            return self._decision_cache[cache_key]

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

        # PROMPT mode — needs interactive approval from the conversation runtime
        if self.mode == PermissionMode.PROMPT:
            # Return a special "needs prompt" deny that the runtime should intercept
            return PermissionDeny(
                reason=f"__NEEDS_PROMPT__:{tool_name}:{required.value}"
            )

        # Default: allow
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
