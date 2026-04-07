"""Slash command registry and specifications.

Maps to: rust/crates/commands/src/lib.rs (SlashCommandSpec, 165+ command specs)
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


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
    interactive_only: bool = False


class CommandSource(enum.Enum):
    BUILTIN = "builtin"
    INTERNAL_ONLY = "internal_only"
    FEATURE_GATED = "feature_gated"
    PLUGIN = "plugin"
    SKILL = "skill"


@dataclass
class CommandManifestEntry:
    name: str
    source: CommandSource = CommandSource.BUILTIN


# ---------------------------------------------------------------------------
# All slash command specs (matching Rust SLASH_COMMAND_SPECS)
# ---------------------------------------------------------------------------

SLASH_COMMAND_SPECS: list[SlashCommandSpec] = [
    # -- Core commands --
    SlashCommandSpec(
        name="help", summary="Show available commands",
        argument_hint="[command]", category="core",
    ),
    SlashCommandSpec(
        name="quit", aliases=["exit", "q"],
        summary="Exit the REPL", category="core",
    ),
    SlashCommandSpec(
        name="clear", summary="Clear conversation history",
        argument_hint="[--confirm]", resume_supported=True, category="core",
    ),
    SlashCommandSpec(
        name="compact", summary="Compact session history to reduce token usage",
        resume_supported=True, category="core",
    ),
    SlashCommandSpec(
        name="cost", summary="Show token usage and estimated costs",
        resume_supported=True, category="core",
    ),
    SlashCommandSpec(
        name="status", summary="Show session status and environment info",
        resume_supported=True, category="core",
    ),

    # -- Model & permissions --
    SlashCommandSpec(
        name="model", summary="Show or change the active model",
        argument_hint="[model_name]", category="model",
    ),
    SlashCommandSpec(
        name="permissions", summary="Show or change permission mode",
        argument_hint="[read-only|workspace-write|danger-full-access]",
        category="model",
    ),

    # -- Session management --
    SlashCommandSpec(
        name="resume", summary="Resume a previous session",
        argument_hint="[session_id|latest]", resume_supported=True,
        category="session",
    ),
    SlashCommandSpec(
        name="session", summary="Session operations",
        argument_hint="[list|show|fork|switch|delete]", category="session",
    ),
    SlashCommandSpec(
        name="export", summary="Export conversation transcript",
        argument_hint="[path]", resume_supported=True, category="session",
    ),

    # -- Configuration --
    SlashCommandSpec(
        name="config", summary="Show configuration",
        argument_hint="[section]", resume_supported=True, category="config",
    ),
    SlashCommandSpec(
        name="sandbox", summary="Show sandbox status and configuration",
        resume_supported=True, category="config",
    ),
    SlashCommandSpec(
        name="init", summary="Initialize project with CLAUDE.md",
        resume_supported=True, category="config",
    ),

    # -- Tool management --
    SlashCommandSpec(
        name="mcp", summary="Manage MCP servers",
        argument_hint="[list|show <server>|help]",
        resume_supported=True, category="tools",
    ),
    SlashCommandSpec(
        name="plugins", summary="Manage plugins",
        argument_hint="[list|install|enable|disable|uninstall]",
        category="tools",
    ),
    SlashCommandSpec(
        name="agents", summary="List available agents",
        argument_hint="[list]", resume_supported=True, category="tools",
    ),
    SlashCommandSpec(
        name="skills", summary="List or invoke skills",
        argument_hint="[list|<skill_name>]", resume_supported=True,
        category="tools",
    ),

    # -- Info & diagnostics --
    SlashCommandSpec(
        name="version", summary="Show version information",
        resume_supported=True, category="info",
    ),
    SlashCommandSpec(
        name="doctor", summary="Run diagnostic health checks",
        resume_supported=True, category="info",
    ),
    SlashCommandSpec(
        name="memory", summary="Show project memory files",
        resume_supported=True, category="info",
    ),
    SlashCommandSpec(
        name="diff", summary="Show git diff of current changes",
        resume_supported=True, category="info",
    ),

    # -- Auth --
    SlashCommandSpec(
        name="login", summary="Authenticate with OAuth",
        category="auth", interactive_only=True,
    ),
    SlashCommandSpec(
        name="logout", summary="Clear stored credentials",
        category="auth", interactive_only=True,
    ),

    # -- Advanced / Interactive-only --
    SlashCommandSpec(
        name="vim", summary="Toggle vim mode",
        category="advanced", interactive_only=True,
    ),
    SlashCommandSpec(
        name="fast", summary="Toggle fast output mode",
        category="advanced", interactive_only=True,
    ),
    SlashCommandSpec(
        name="theme", summary="Change color theme",
        argument_hint="[dark|light|default]",
        category="advanced", interactive_only=True,
    ),
    SlashCommandSpec(
        name="voice", summary="Toggle voice input mode",
        category="advanced", interactive_only=True,
    ),
    SlashCommandSpec(
        name="branch", summary="Show or switch git branch",
        argument_hint="[branch_name]", category="advanced",
    ),
    SlashCommandSpec(
        name="rewind", summary="Rewind conversation to a previous point",
        argument_hint="[steps]", category="advanced", interactive_only=True,
    ),
    SlashCommandSpec(
        name="hooks", summary="Show configured hooks",
        category="advanced",
    ),
    SlashCommandSpec(
        name="context", summary="Show current context window usage",
        category="advanced",
    ),
    SlashCommandSpec(
        name="output-style", aliases=["brief", "verbose"],
        summary="Change output verbosity",
        argument_hint="[brief|verbose|default]", category="advanced",
    ),
    SlashCommandSpec(
        name="effort", summary="Set reasoning effort level",
        argument_hint="[low|medium|high]", category="advanced",
    ),

    # -- Task & workflow --
    SlashCommandSpec(
        name="plan", summary="Enter plan mode for implementation design",
        category="workflow", interactive_only=True,
    ),
    SlashCommandSpec(
        name="review", summary="Review code changes",
        category="workflow", interactive_only=True,
    ),
    SlashCommandSpec(
        name="tasks", summary="Show or manage task list",
        argument_hint="[list|add|complete]", category="workflow",
    ),
    SlashCommandSpec(
        name="commit", summary="Create a git commit",
        category="workflow", interactive_only=True,
    ),
    SlashCommandSpec(
        name="bughunter", summary="Search for bugs in scope",
        argument_hint="[scope]", category="workflow", interactive_only=True,
    ),

    # -- Misc interactive --
    SlashCommandSpec(
        name="share", summary="Share conversation",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="feedback", summary="Send feedback",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="upgrade", summary="Check for updates",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="stats", summary="Show usage statistics",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="files", summary="List files in context",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="summary", summary="Summarize conversation",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="desktop", summary="Open desktop app",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="advisor", summary="AI advisor mode",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="stickers", summary="Show sticker collection",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="insights", summary="Show project insights",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="thinkback", summary="Review thinking process",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="release-notes", summary="Show release notes",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="security-review", summary="Run security review",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="keybindings", summary="Show or edit keybindings",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="privacy-settings", summary="Manage privacy settings",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="ide", summary="Open IDE integration",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="tag", summary="Tag current conversation",
        argument_hint="[tag_name]", category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="rename", summary="Rename current session",
        argument_hint="[new_name]", category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="copy", summary="Copy last response to clipboard",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="usage", summary="Show detailed usage metrics",
        category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="color", summary="Change color settings",
        argument_hint="[setting]", category="misc", interactive_only=True,
    ),
    SlashCommandSpec(
        name="add-dir", summary="Add directory to context",
        argument_hint="<path>", category="misc", interactive_only=True,
    ),
]


# ---------------------------------------------------------------------------
# Command registry
# ---------------------------------------------------------------------------

class CommandRegistry:
    """Registry of all available slash commands.

    Maps to: rust/crates/commands/src/lib.rs (command registry)
    """

    def __init__(self) -> None:
        self._commands: dict[str, SlashCommandSpec] = {}
        self._by_category: dict[str, list[SlashCommandSpec]] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        for spec in SLASH_COMMAND_SPECS:
            self._commands[spec.name] = spec
            for alias in spec.aliases:
                self._commands[alias] = spec
            # Index by category
            cat = spec.category
            if cat not in self._by_category:
                self._by_category[cat] = []
            self._by_category[cat].append(spec)

    def get(self, name: str) -> SlashCommandSpec | None:
        return self._commands.get(name.lstrip("/").lower())

    def all_specs(self) -> list[SlashCommandSpec]:
        """Get all unique command specs (no alias duplicates)."""
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

    def resume_supported(self) -> list[SlashCommandSpec]:
        """Get commands that support --resume mode."""
        return [s for s in self.all_specs() if s.resume_supported]

    def interactive_only(self) -> list[SlashCommandSpec]:
        """Get commands that only work in interactive REPL."""
        return [s for s in self.all_specs() if s.interactive_only]

    def register_plugin_command(self, name: str, summary: str = "") -> None:
        """Register a command from a plugin."""
        spec = SlashCommandSpec(
            name=name, summary=summary,
            source="plugin", category="plugin",
        )
        self._commands[name] = spec

    def register_skill_command(self, name: str, summary: str = "") -> None:
        """Register a command from a skill definition."""
        spec = SlashCommandSpec(
            name=name, summary=summary,
            source="skill", category="skill",
        )
        self._commands[name] = spec


# Module singleton
_registry: CommandRegistry | None = None


def get_command_registry() -> CommandRegistry:
    global _registry
    if _registry is None:
        _registry = CommandRegistry()
    return _registry
