"""Slash command parsing with full variant matching and typo-tolerant suggestions.

Maps to: rust/crates/commands/src/lib.rs (parsing, SlashCommand enum)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from axion.commands.registry import CommandRegistry, SlashCommandSpec, get_command_registry

# ---------------------------------------------------------------------------
# Parsed command variants
# ---------------------------------------------------------------------------

@dataclass
class ParsedCommand:
    """Result of parsing a slash command input."""

    name: str
    args: str = ""
    spec: SlashCommandSpec | None = None
    # Structured arguments for commands with specific parsing
    parsed_args: dict[str, Any] = field(default_factory=dict)


@dataclass
class CommandParseError:
    """Error when a slash command cannot be parsed."""

    input_text: str
    message: str
    suggestions: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Argument parsers for specific commands
# ---------------------------------------------------------------------------

VALID_PERMISSION_MODES = {"read-only", "workspace-write", "danger-full-access", "prompt", "allow"}


def _parse_model_args(args: str) -> dict[str, Any]:
    """Parse /model [name] arguments."""
    if not args.strip():
        return {"action": "show"}
    return {"action": "set", "model": args.strip()}


def _parse_permissions_args(args: str) -> dict[str, Any]:
    """Parse /permissions [mode] arguments."""
    mode = args.strip().lower()
    if not mode:
        return {"action": "show"}
    if mode not in VALID_PERMISSION_MODES:
        return {"action": "invalid", "mode": mode, "valid": sorted(VALID_PERMISSION_MODES)}
    return {"action": "set", "mode": mode}


def _parse_session_args(args: str) -> dict[str, Any]:
    """Parse /session [action] [target] arguments."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "show"
    target = parts[1].strip() if len(parts) > 1 else ""

    if action in ("list", "ls"):
        return {"action": "list"}
    if action in ("show", "info"):
        return {"action": "show", "target": target}
    if action == "fork":
        return {"action": "fork", "branch_name": target or None}
    if action == "switch":
        return {"action": "switch", "target": target}
    if action in ("delete", "rm"):
        return {"action": "delete", "target": target}
    # Default: show current
    return {"action": "show"}


def _parse_mcp_args(args: str) -> dict[str, Any]:
    """Parse /mcp [action] [target] arguments."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else ""

    if action in ("list", "ls", ""):
        return {"action": "list"}
    if action == "show":
        return {"action": "show", "server": target}
    if action == "help":
        return {"action": "help"}
    return {"action": action, "target": target}


def _parse_plugins_args(args: str) -> dict[str, Any]:
    """Parse /plugins [action] [target] arguments."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "list"
    target = parts[1].strip() if len(parts) > 1 else ""

    return {"action": action, "target": target}


def _parse_effort_args(args: str) -> dict[str, Any]:
    """Parse /effort [level] arguments."""
    level = args.strip().lower()
    if not level:
        return {"action": "show"}
    if level in ("low", "medium", "high"):
        return {"action": "set", "level": level}
    return {"action": "invalid", "level": level}


def _parse_output_style_args(args: str) -> dict[str, Any]:
    """Parse /output-style [style] arguments."""
    style = args.strip().lower()
    if not style:
        return {"action": "show"}
    if style in ("brief", "verbose", "default"):
        return {"action": "set", "style": style}
    return {"action": "invalid", "style": style}


# Command-specific parsers
_ARGUMENT_PARSERS: dict[str, Any] = {
    "model": _parse_model_args,
    "permissions": _parse_permissions_args,
    "session": _parse_session_args,
    "mcp": _parse_mcp_args,
    "plugins": _parse_plugins_args,
    "effort": _parse_effort_args,
    "output-style": _parse_output_style_args,
}


# ---------------------------------------------------------------------------
# Main parsing function
# ---------------------------------------------------------------------------

def parse_slash_command(
    input_text: str,
    registry: CommandRegistry | None = None,
) -> ParsedCommand | CommandParseError:
    """Parse a slash command from user input.

    Returns ParsedCommand on success, CommandParseError on failure.
    Handles alias resolution, argument parsing, and fuzzy suggestions.
    """
    reg = registry or get_command_registry()

    stripped = input_text.strip()
    if not stripped.startswith("/"):
        return CommandParseError(
            input_text=stripped,
            message="Not a slash command",
            suggestions=[],
        )

    # Split command name and args
    parts = stripped[1:].split(maxsplit=1)
    cmd_name = parts[0].lower() if parts else ""
    cmd_args = parts[1] if len(parts) > 1 else ""

    if not cmd_name:
        return CommandParseError(
            input_text=stripped,
            message="Empty command",
            suggestions=["/help"],
        )

    # Look up in registry
    spec = reg.get(cmd_name)
    if spec is not None:
        # Parse arguments if there's a specific parser
        parsed_args: dict[str, Any] = {}
        parser = _ARGUMENT_PARSERS.get(spec.name)
        if parser:
            parsed_args = parser(cmd_args)

        return ParsedCommand(
            name=spec.name,
            args=cmd_args,
            spec=spec,
            parsed_args=parsed_args,
        )

    # Not found — suggest similar commands
    suggestions = suggest_commands(cmd_name, reg, limit=3)
    return CommandParseError(
        input_text=stripped,
        message=f"Unknown command: /{cmd_name}",
        suggestions=suggestions,
    )


# ---------------------------------------------------------------------------
# Fuzzy suggestions (Levenshtein distance)
# ---------------------------------------------------------------------------

def suggest_commands(
    input_name: str,
    registry: CommandRegistry | None = None,
    limit: int = 3,
) -> list[str]:
    """Suggest similar commands using Levenshtein distance."""
    reg = registry or get_command_registry()
    all_names = [s.name for s in reg.all_specs()]

    try:
        from rapidfuzz import fuzz

        scored = [(name, fuzz.ratio(input_name, name)) for name in all_names]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [f"/{name}" for name, score in scored[:limit] if score > 40]
    except ImportError:
        # Fallback: simple prefix + substring matching
        results: list[str] = []
        for name in all_names:
            if name.startswith(input_name[:2]) or input_name in name:
                results.append(f"/{name}")
                if len(results) >= limit:
                    break
        return results


# ---------------------------------------------------------------------------
# Help rendering
# ---------------------------------------------------------------------------

_CATEGORY_LABELS: dict[str, str] = {
    "core": "Core Commands",
    "model": "Model & Permissions",
    "session": "Session Management",
    "config": "Configuration",
    "tools": "Tool Management",
    "info": "Info & Diagnostics",
    "auth": "Authentication",
    "workflow": "Task & Workflow",
    "advanced": "Advanced",
    "misc": "Miscellaneous",
    "plugin": "Plugin Commands",
    "skill": "Skills",
}

_CATEGORY_ORDER = [
    "core", "model", "session", "config", "tools",
    "info", "auth", "workflow", "advanced",
]


def render_help(
    registry: CommandRegistry | None = None,
    include_interactive_only: bool = True,
    detailed: bool = False,
) -> str:
    """Render categorized help text for all available slash commands."""
    reg = registry or get_command_registry()
    lines: list[str] = ["Available commands:", ""]

    # Group by category in order
    rendered_categories: set[str] = set()
    for cat in _CATEGORY_ORDER:
        specs = reg.by_category(cat)
        if not specs:
            continue
        if False:  # all commands are real now
            pass
        if not specs:
            continue

        rendered_categories.add(cat)
        label = _CATEGORY_LABELS.get(cat, cat.title())
        lines.append(f"  {label}:")

        for spec in sorted(specs, key=lambda s: s.name):
            hint = f" {spec.argument_hint}" if spec.argument_hint else ""
            aliases = ""
            if spec.aliases:
                aliases = f" (aliases: {', '.join('/' + a for a in spec.aliases)})"
            interactive = ""
            lines.append(f"    /{spec.name}{hint} — {spec.summary}{aliases}{interactive}")

        lines.append("")

    # Remaining categories
    for cat in sorted(reg.categories()):
        if cat in rendered_categories:
            continue
        specs = reg.by_category(cat)
        if not specs:
            continue
        label = _CATEGORY_LABELS.get(cat, cat.title())
        lines.append(f"  {label}:")
        for spec in sorted(specs, key=lambda s: s.name):
            hint = f" {spec.argument_hint}" if spec.argument_hint else ""
            lines.append(f"    /{spec.name}{hint} — {spec.summary}")
        lines.append("")

    return "\n".join(lines)


def render_help_detail(
    command_name: str,
    registry: CommandRegistry | None = None,
) -> str | None:
    """Render detailed help for a specific command."""
    reg = registry or get_command_registry()
    spec = reg.get(command_name)
    if spec is None:
        return None

    lines = [
        f"/{spec.name}",
        f"  {spec.summary}",
    ]
    if spec.argument_hint:
        lines.append(f"  Usage: /{spec.name} {spec.argument_hint}")
    if spec.aliases:
        lines.append(f"  Aliases: {', '.join('/' + a for a in spec.aliases)}")
    if spec.resume_supported:
        lines.append("  Supports --resume mode")
    if False:
        lines.append("  Interactive REPL only")
    lines.append(f"  Category: {spec.category}")

    return "\n".join(lines)
