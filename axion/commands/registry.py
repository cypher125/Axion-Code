"""Slash command registry — ONLY commands that actually have handlers.

No fake commands. If it shows in /help, it works.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


@dataclass
class SlashCommandSpec:
    """Metadata for a slash command."""

    name: str
    aliases: list[str] = field(default_factory=list)
    summary: str = ""
    argument_hint: str | None = None
    resume_supported: bool = False
    source: str = "builtin"
    category: str = "general"


class CommandSource(enum.Enum):
    BUILTIN = "builtin"
    PLUGIN = "plugin"
    SKILL = "skill"


@dataclass
class CommandManifestEntry:
    name: str
    source: CommandSource = CommandSource.BUILTIN


# ---------------------------------------------------------------------------
# ONLY commands that have working handlers
# ---------------------------------------------------------------------------

SLASH_COMMAND_SPECS: list[SlashCommandSpec] = [
    # -- Core --
    SlashCommandSpec(name="help", summary="Show available commands", argument_hint="[command]", category="core"),
    SlashCommandSpec(name="quit", aliases=["exit", "q"], summary="Exit the REPL", category="core"),
    SlashCommandSpec(name="clear", summary="Clear conversation history", category="core"),
    SlashCommandSpec(name="compact", summary="Compact session history to reduce tokens", category="core"),
    SlashCommandSpec(name="cost", summary="Show token usage and costs", category="core"),
    SlashCommandSpec(name="status", summary="Show session status", category="core"),

    # -- Model --
    SlashCommandSpec(name="model", summary="Show or switch AI model", argument_hint="[opus|sonnet|haiku|gpt-4o|grok-2|llama3.1]", category="model"),
    SlashCommandSpec(name="models", summary="List available Ollama models", category="model"),
    SlashCommandSpec(name="permissions", summary="Show or change permission mode", argument_hint="[allow|prompt|read-only]", category="model"),

    # -- Session --
    SlashCommandSpec(name="session", summary="Manage sessions (list/switch/new/fork/delete)", argument_hint="[list|switch|new|fork|delete]", category="session"),
    SlashCommandSpec(name="resume", summary="Resume a previous session", argument_hint="[session_id|latest]", category="session"),
    SlashCommandSpec(name="export", summary="Export transcript to markdown", argument_hint="[filename]", category="session"),
    SlashCommandSpec(name="share", summary="Share session with teammates", argument_hint="[file|import <path>]", category="session"),

    # -- Config & Setup --
    SlashCommandSpec(name="config", summary="Show loaded configuration", category="config"),
    SlashCommandSpec(name="init", summary="Create AXION.md for your project", category="config"),
    SlashCommandSpec(name="sandbox", summary="Show sandbox status", category="config"),
    SlashCommandSpec(name="license", summary="Show license status and upgrade path", category="config"),

    # -- Tools & Plugins --
    SlashCommandSpec(name="mcp", summary="Manage MCP servers", argument_hint="[list|show|help]", category="tools"),
    SlashCommandSpec(name="plugins", summary="Manage plugins", argument_hint="[list|install|enable|disable]", category="tools"),
    SlashCommandSpec(name="agents", summary="List available agents", category="tools"),
    SlashCommandSpec(name="skills", summary="List available skills", category="tools"),

    # -- Info --
    SlashCommandSpec(name="version", summary="Show version", category="info"),
    SlashCommandSpec(name="doctor", summary="Run health checks", category="info"),
    SlashCommandSpec(name="memory", summary="Show project memory", category="info"),
    SlashCommandSpec(name="diff", summary="Show git changes with syntax highlighting", category="info"),

    # -- Auth --
    SlashCommandSpec(name="login", summary="Save API key (axion login --provider openai)", category="auth"),
    SlashCommandSpec(name="logout", summary="Remove saved credentials", category="auth"),

    # -- Workflow --
    SlashCommandSpec(name="plan", summary="Plan before coding (read-only exploration)", argument_hint="<task>", category="workflow"),
    SlashCommandSpec(name="commit", summary="Auto-commit with AI message", argument_hint="[message]", category="workflow"),
    SlashCommandSpec(name="undo", summary="Revert last change (git reset)", argument_hint="[hard|file.py]", category="workflow"),
    SlashCommandSpec(name="review", summary="AI code review of recent changes", argument_hint="[file|HEAD~N]", category="workflow"),
    SlashCommandSpec(name="test", summary="Generate tests for a file", argument_hint="<file> [pytest|jest]", category="workflow"),
    SlashCommandSpec(name="init-project", aliases=["scaffold"], summary="Scaffold project from template", argument_hint="[react|django|fastapi|express|cli]", category="workflow"),
    SlashCommandSpec(name="security-review", summary="AI security audit of code", argument_hint="[file]", category="workflow"),

    # -- Utility --
    SlashCommandSpec(name="context", summary="Show context window usage (tokens/capacity)", category="utility"),
    SlashCommandSpec(name="branch", summary="Show or switch git branch", argument_hint="[branch_name]", category="utility"),
    SlashCommandSpec(name="hooks", summary="Show configured hooks", category="utility"),
    SlashCommandSpec(name="copy", summary="Copy last response to clipboard", category="utility"),
    SlashCommandSpec(name="rename", summary="Rename current session", argument_hint="<new_name>", category="utility"),
    SlashCommandSpec(name="files", summary="List files referenced in this session", category="utility"),
    SlashCommandSpec(name="summary", summary="AI summarizes the conversation so far", category="utility"),
    SlashCommandSpec(name="stats", summary="Show detailed usage statistics", category="utility"),
    SlashCommandSpec(name="upgrade", summary="Show upgrade path (Free → Pro → Team)", category="utility"),
]


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

class CommandRegistry:
    """Registry of slash commands — only commands with working handlers."""

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommandSpec] = {}
        self._by_category: dict[str, list[SlashCommandSpec]] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        for spec in SLASH_COMMAND_SPECS:
            self._commands[spec.name] = spec
            for alias in spec.aliases:
                self._commands[alias] = spec
            cat = spec.category
            if cat not in self._by_category:
                self._by_category[cat] = []
            self._by_category[cat].append(spec)

    def get(self, name: str) -> SlashCommandSpec | None:
        return self._commands.get(name.lstrip("/").lower())

    def all_specs(self) -> list[SlashCommandSpec]:
        seen: set[str] = set()
        specs: list[SlashCommandSpec] = []
        for spec in self._commands.values():
            if spec.name not in seen:
                seen.add(spec.name)
                specs.append(spec)
        return specs

    def command_names(self) -> list[str]:
        return list(self._commands.keys())

    def by_category(self, category: str) -> list[SlashCommandSpec]:
        return self._by_category.get(category, [])

    def categories(self) -> list[str]:
        return sorted(self._by_category.keys())

    def register_plugin_command(self, name: str, summary: str = "") -> None:
        spec = SlashCommandSpec(name=name, summary=summary, source="plugin", category="plugin")
        self._commands[name] = spec

    def register_skill_command(self, name: str, summary: str = "") -> None:
        spec = SlashCommandSpec(name=name, summary=summary, source="skill", category="skill")
        self._commands[name] = spec


_registry: CommandRegistry | None = None


def get_command_registry() -> CommandRegistry:
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry
