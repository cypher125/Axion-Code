"""Anthropic request profile and client identity.

Maps to: rust/crates/telemetry/src/lib.rs (AnthropicRequestProfile, ClientIdentity)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_APP_NAME = "axion-code"
DEFAULT_RUNTIME = "python"
DEFAULT_AGENTIC_BETA = "claude-code-20250219"
DEFAULT_PROMPT_CACHING_SCOPE_BETA = "prompt-caching-scope-2026-01-05"


@dataclass
class ClientIdentity:
    """Application identity for API requests."""

    app_name: str = DEFAULT_APP_NAME
    app_version: str = "1.0.0"
    runtime: str = DEFAULT_RUNTIME

    def user_agent(self) -> str:
        return f"{self.app_name}/{self.app_version}"


@dataclass
class AnthropicRequestProfile:
    """HTTP request configuration for Anthropic API."""

    anthropic_version: str = DEFAULT_ANTHROPIC_VERSION
    client_identity: ClientIdentity = field(default_factory=ClientIdentity)
    betas: list[str] = field(
        default_factory=lambda: [DEFAULT_AGENTIC_BETA, DEFAULT_PROMPT_CACHING_SCOPE_BETA]
    )
    extra_body: dict[str, Any] = field(default_factory=dict)

    def header_pairs(self) -> dict[str, str]:
        """Generate HTTP headers for the request."""
        headers = {
            "anthropic-version": self.anthropic_version,
            "user-agent": self.client_identity.user_agent(),
        }
        if self.betas:
            headers["anthropic-beta"] = ",".join(self.betas)
        return headers
