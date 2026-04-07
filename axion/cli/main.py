"""CLI entry point for Axion Code.

Maps to: rust/crates/rusty-claude-cli/src/main.rs

Comprehensive CLI with:
- All subcommands (status, sandbox, agents, mcp, skills, plugins, system-prompt,
  login, logout, doctor, init, version, resume, export)
- Full interactive REPL with 40+ slash commands
- JSON output mode for scripting
- Session persistence and resume
- Tool display with box-drawing characters
- Permission prompting
- OAuth login/logout
- Configuration display
- Transcript export
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import click
from rich.console import Console
from rich.markdown import Markdown

from axion import __version__
from axion.api.client import (
    ProviderClient,
    resolve_model_alias,
)
from axion.cli.render import CLAW_THEME, MarkdownStreamState, TerminalRenderer
from axion.commands.handlers.agents import handle_agents_command
from axion.commands.handlers.mcp import handle_mcp_command
from axion.commands.handlers.plugins import handle_plugins_command
from axion.commands.handlers.skills import handle_skills_command
from axion.commands.parsing import (
    CommandParseError,
    ParsedCommand,
    parse_slash_command,
    render_help,
)
from axion.plugins.manager import PluginManager
from axion.runtime.compact import (
    CompactionConfig,
    compact_session,
    estimate_session_tokens,
)
from axion.runtime.config import ConfigLoader, RuntimeConfig
from axion.runtime.conversation import ConversationRuntime, TurnSummary
from axion.runtime.oauth import (
    clear_oauth_credentials,
    load_oauth_credentials,
)
from axion.runtime.permissions import (
    PermissionMode,
    PermissionPolicy,
    PermissionPromptDecision,
    PermissionRequest,
)
from axion.runtime.prompt import SystemPromptBuilder
from axion.runtime.sandbox import detect_sandbox
from axion.runtime.session import (
    Session,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from axion.runtime.usage import UsageTracker, format_usd
from axion.tools.registry import BuiltinToolExecutor, get_tool_registry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_OAUTH_CALLBACK_PORT = 4545
SESSION_DIR = ".axion/sessions"
HISTORY_FILE = ".axion/repl_history"
MAX_SESSION_LIST = 20

console = Console(theme=CLAW_THEME)
renderer = TerminalRenderer(console=console)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _session_dir(cwd: Path | None = None) -> Path:
    """Return the session directory, creating it if needed."""
    base = cwd or Path.cwd()
    d = base / SESSION_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_path_for_id(session_id: str, cwd: Path | None = None) -> Path:
    """Return the JSONL file path for a given session ID."""
    return _session_dir(cwd) / f"{session_id}.jsonl"


def _list_sessions(cwd: Path | None = None, limit: int = MAX_SESSION_LIST) -> list[Path]:
    """List session files sorted by modification time (newest first)."""
    d = _session_dir(cwd)
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:limit]


def _find_latest_session(cwd: Path | None = None) -> Path | None:
    """Find the most recently modified session file."""
    sessions = _list_sessions(cwd, limit=1)
    return sessions[0] if sessions else None


def _resolve_session(identifier: str, cwd: Path | None = None) -> Path | None:
    """Resolve a session from an ID, file path, or 'latest'."""
    if identifier == "latest":
        return _find_latest_session(cwd)

    # Try as a file path first
    as_path = Path(identifier)
    if as_path.exists() and as_path.suffix == ".jsonl":
        return as_path

    # Try as a session ID
    candidate = _session_path_for_id(identifier, cwd)
    if candidate.exists():
        return candidate

    # Try partial ID match
    d = _session_dir(cwd)
    for f in d.glob("*.jsonl"):
        if f.stem.startswith(identifier):
            return f

    return None


def _git_branch() -> str | None:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


def _git_status_short() -> str | None:
    """Get short git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "(clean)"
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return None


class CliPermissionPrompter:
    """Interactive permission prompter for the CLI REPL.

    Shows tool details and asks [y/N/a] where:
      y = allow this once
      a = allow always (remember for this tool)
      N = deny (default)

    Implements the PermissionPrompter protocol.
    """

    def __init__(self) -> None:
        self._stop_spinner_fn: Any = None  # Set by REPL to stop spinner

    async def decide(self, request: PermissionRequest) -> PermissionPromptDecision:
        """Show an interactive prompt and wait for user decision."""
        # Stop the spinner before showing the prompt
        if self._stop_spinner_fn:
            self._stop_spinner_fn()
        console.print()
        console.print("[bold yellow]Permission required[/bold yellow]")
        console.print(f"  Tool: [bold]{request.tool_name}[/bold]")
        console.print(f"  Mode: {request.current_mode.value} → needs {request.required_mode.value}")
        if request.reason:
            console.print(f"  Reason: {request.reason}")
        if request.input_json:
            display = request.input_json[:300]
            if len(request.input_json) > 300:
                display += "..."
            console.print(f"  Input: [dim]{display}[/dim]")
        console.print()

        try:
            answer = console.input("[yellow]Allow? [y/N/a(lways)]: [/yellow]").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("[dim]Denied.[/dim]")
            return PermissionPromptDecision.DENY

        if answer in ("y", "yes"):
            console.print("[green]Allowed (once).[/green]")
            return PermissionPromptDecision.ALLOW
        if answer in ("a", "always"):
            console.print("[green]Allowed (always for this tool).[/green]")
            return PermissionPromptDecision.ALLOW

        console.print("[dim]Denied.[/dim]")
        return PermissionPromptDecision.DENY


def _render_tool_use(tool_name: str, tool_input: str) -> None:
    """Display a tool invocation with box-drawing characters."""
    try:
        parsed = json.loads(tool_input) if tool_input else {}
    except json.JSONDecodeError:
        parsed = {}

    # Header line
    console.print(f"[bold yellow]\u256d\u2500 {tool_name}[/bold yellow]")

    # Show key parameters
    if isinstance(parsed, dict):
        for key, value in list(parsed.items())[:5]:
            val_str = str(value)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            console.print(f"[dim]\u2502  {key}: {val_str}[/dim]")

    console.print("[dim]\u2570\u2500[/dim]")


def _render_tool_result(tool_name: str, output: str, is_error: bool) -> None:
    """Display a tool result with success/failure indicator."""
    if is_error:
        console.print(f"[red]\u2717 {tool_name}: {output[:500]}[/red]")
    else:
        truncated = output[:500] + "..." if len(output) > 500 else output
        console.print(f"[green]\u2713 {tool_name}[/green]")
        if truncated.strip():
            for line in truncated.splitlines()[:10]:
                console.print(f"  [dim]{line}[/dim]")
            if len(output.splitlines()) > 10:
                console.print(f"  [dim]... ({len(output.splitlines())} lines total)[/dim]")


def _build_json_output(summary: TurnSummary, model: str) -> dict[str, Any]:
    """Build structured JSON output from a turn summary."""
    tool_uses_out: list[dict[str, Any]] = []
    tool_results_out: list[dict[str, Any]] = []

    for msg in summary.assistant_messages:
        for block in msg.blocks:
            if isinstance(block, ToolUseBlock):
                tool_uses_out.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })

    for msg in summary.tool_results:
        for block in msg.blocks:
            if isinstance(block, ToolResultBlock):
                tool_results_out.append({
                    "tool_use_id": block.tool_use_id,
                    "tool_name": block.tool_name,
                    "output": block.output,
                    "is_error": block.is_error,
                })

    cost = summary.usage.estimate_cost_usd()
    return {
        "message": summary.text_output,
        "model": model,
        "iterations": summary.iterations,
        "tool_uses": tool_uses_out,
        "tool_results": tool_results_out,
        "usage": {
            "input_tokens": summary.usage.input_tokens,
            "output_tokens": summary.usage.output_tokens,
            "cache_creation_input_tokens": summary.usage.cache_creation_input_tokens,
            "cache_read_input_tokens": summary.usage.cache_read_input_tokens,
            "total_tokens": summary.usage.total_tokens(),
        },
        "estimated_cost": cost.total_cost_usd(),
    }


def _load_config() -> RuntimeConfig:
    """Load merged configuration from all sources."""
    loader = ConfigLoader(project_dir=Path.cwd())
    return loader.load()


def _create_plugin_manager() -> PluginManager:
    """Create and initialize the plugin manager."""
    manager = PluginManager()
    manager.discover_plugins()
    return manager


def _export_transcript(session: Session, output_path: Path) -> None:
    """Export a session transcript to a clean, readable markdown file."""
    lines: list[str] = []

    # Header
    created = datetime.fromtimestamp(session.created_at_ms / 1000)
    lines.append("# Axion Code — Session Transcript")
    lines.append("")
    lines.append(f"> **Session**: `{session.session_id}`")
    lines.append(f"> **Date**: {created.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"> **Messages**: {session.message_count()}")
    if session.fork:
        lines.append(f"> **Forked from**: `{session.fork.parent_session_id}`")
    if session.compaction:
        lines.append(f"> **Compactions**: {session.compaction.count}")
    lines.append("")
    lines.append("---")
    lines.append("")

    turn_number = 0
    for msg in session.messages:
        role = msg.role.value

        if role == "user":
            turn_number += 1
            lines.append(f"## Turn {turn_number}")
            lines.append("")
            lines.append("### You")
            lines.append("")
        elif role == "assistant":
            lines.append("### Axion")
            lines.append("")
        elif role == "system":
            lines.append("### System")
            lines.append("")

        for block in msg.blocks:
            if isinstance(block, TextBlock):
                lines.append(block.text)
                lines.append("")
            elif isinstance(block, ToolUseBlock):
                lines.append("<details>")
                lines.append(f"<summary>🔧 <strong>{block.name}</strong></summary>")
                lines.append("")
                lines.append("```json")
                # Pretty-print the input JSON
                try:
                    import json as _json
                    parsed = _json.loads(block.input) if block.input else {}
                    lines.append(_json.dumps(parsed, indent=2))
                except Exception:
                    lines.append(block.input)
                lines.append("```")
                lines.append("</details>")
                lines.append("")
            elif isinstance(block, ToolResultBlock):
                icon = "❌" if block.is_error else "✅"
                status = "Error" if block.is_error else "Result"
                lines.append("<details>")
                lines.append(f"<summary>{icon} <strong>{block.tool_name}</strong> — {status}</summary>")
                lines.append("")
                lines.append("```")
                output = block.output
                if len(output) > 3000:
                    output = output[:3000] + "\n... (truncated)"
                lines.append(output)
                lines.append("```")
                lines.append("</details>")
                lines.append("")

        if role == "assistant" and msg.usage:
            cost = msg.usage.estimate_cost_usd()
            lines.append(
                f"*Tokens: {msg.usage.total_tokens():,} | "
                f"Cost: ${cost.total_cost_usd():.4f}*"
            )
            lines.append("")

        lines.append("---")
        lines.append("")

    # Footer
    lines.append(f"*Exported by Axion Code on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Runtime builder
# ---------------------------------------------------------------------------

def _build_runtime(
    model: str,
    permission_mode: str,
    session: Session,
    config: RuntimeConfig | None = None,
    on_text_delta: Any = None,
    on_tool_use: Any = None,
    on_tool_result: Any = None,
) -> tuple[ConversationRuntime, ProviderClient]:
    """Build a ConversationRuntime with all components wired up."""
    cfg = config or _load_config()

    # Resolve model: CLI flag -> config -> env -> default
    effective_model = resolve_model_alias(model)
    if effective_model == resolve_model_alias(DEFAULT_MODEL) and cfg.feature_config.model:
        effective_model = resolve_model_alias(cfg.feature_config.model)

    # Build provider
    provider = ProviderClient.from_model(effective_model)

    # Build system prompt (render to string, not list)
    prompt_builder = SystemPromptBuilder.for_cwd()
    system_prompt = prompt_builder.render()

    # Build permission policy
    effective_perm = permission_mode
    if effective_perm == "allow" and cfg.feature_config.permission_mode:
        effective_perm = cfg.feature_config.permission_mode
    mode = PermissionMode(effective_perm) if effective_perm != "allow" else PermissionMode.ALLOW
    policy = PermissionPolicy(mode=mode)

    # Build tool executor
    tool_executor = BuiltinToolExecutor(cwd=str(Path.cwd()))

    runtime = ConversationRuntime(
        session=session,
        provider=provider,
        tool_executor=tool_executor,
        permission_policy=policy,
        permission_prompter=CliPermissionPrompter(),
        system_prompt=system_prompt,
        model=effective_model,
        on_text_delta=on_text_delta,
        on_tool_use=on_tool_use,
        on_tool_result=on_tool_result,
    )

    return runtime, provider


# ---------------------------------------------------------------------------
# One-shot execution
# ---------------------------------------------------------------------------

async def run_one_shot(
    prompt: str,
    model: str,
    permission_mode: str,
    output_format: str = "text",
) -> int:
    """Execute a single prompt and print the streaming response."""
    config = _load_config()
    session = Session()

    text_buffer: list[str] = []
    md_stream = MarkdownStreamState()

    def on_text_delta(text: str) -> None:
        text_buffer.append(text)
        if output_format == "json":
            return
        # Use markdown streaming: buffer until safe boundary, then render
        rendered = md_stream.push(renderer, text)
        if rendered:
            console.print(Markdown(rendered), end="")

    runtime, provider = _build_runtime(
        model=model,
        permission_mode=permission_mode,
        session=session,
        config=config,
        on_text_delta=on_text_delta,
    )

    try:
        summary = await runtime.run_turn(prompt)

        # Flush any remaining markdown
        if output_format != "json":
            remaining = md_stream.flush(renderer)
            if remaining:
                console.print(Markdown(remaining))

        if output_format == "json":
            json_out = _build_json_output(summary, runtime.model)
            click.echo(json.dumps(json_out, indent=2))
        else:
            console.print()  # Newline after streaming

            # Display tool activity
            for msg in summary.assistant_messages:
                for block in msg.blocks:
                    if isinstance(block, ToolUseBlock):
                        _render_tool_use(block.name, block.input)
            for msg in summary.tool_results:
                for block in msg.blocks:
                    if isinstance(block, ToolResultBlock):
                        _render_tool_result(block.tool_name, block.output, block.is_error)

            # Print usage
            if summary.usage.total_tokens() > 0:
                cost = summary.usage.estimate_cost_usd()
                console.print(
                    f"\n[dim]Tokens: {summary.usage.total_tokens()} | "
                    f"Cost: {format_usd(cost.total_cost_usd())} | "
                    f"Turns: {summary.iterations}[/dim]"
                )
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        return 130
    except Exception as exc:
        if output_format == "json":
            click.echo(json.dumps({"error": str(exc)}, indent=2))
        else:
            console.print(f"\n[red]Error: {exc}[/red]")
        return 1
    finally:
        await provider.close()

    return 0


# ---------------------------------------------------------------------------
# REPL slash command dispatcher
# ---------------------------------------------------------------------------

async def _handle_slash_command(
    user_input: str,
    runtime: ConversationRuntime,
    session: Session,
    plugin_manager: PluginManager,
    config: RuntimeConfig,
) -> str | None:
    """Handle a slash command. Returns None to signal exit, or a status message."""
    result = parse_slash_command(user_input)

    if isinstance(result, CommandParseError):
        msg = result.message
        if result.suggestions:
            msg += f"\n  Did you mean: {', '.join(result.suggestions)}?"
        return msg

    assert isinstance(result, ParsedCommand)
    cmd = result.name
    args = result.args

    # --- Exit commands ---
    if cmd in ("quit", "exit", "q"):
        return None

    # --- Help ---
    if cmd == "help":
        return render_help()

    # --- Clear ---
    if cmd == "clear":
        session.messages.clear()
        return "Session cleared."

    # --- Cost ---
    if cmd == "cost":
        lines = runtime.usage_tracker.summary_lines()
        return "\n".join(lines)

    # --- Status ---
    if cmd == "status":
        return _format_status(runtime, session)

    # --- Model ---
    if cmd == "model":
        if args.strip():
            new_model = resolve_model_alias(args.strip())
            runtime.model = new_model
            return f"Model set to: {new_model}"
        return f"Current model: {runtime.model}"

    # --- Compact ---
    if cmd == "compact":
        tokens_before = estimate_session_tokens(session)
        compaction_config = CompactionConfig()
        if args.strip():
            try:
                compaction_config.max_tokens = int(args.strip())
            except ValueError:
                return "Usage: /compact [max_tokens]"
        cr = compact_session(session, compaction_config)
        if cr is None:
            return f"No compaction needed (estimated {tokens_before} tokens)."
        return (
            f"Compacted: removed {cr.removed_count} messages, "
            f"{cr.estimated_tokens_before} -> {cr.estimated_tokens_after} tokens."
        )

    # --- Permissions ---
    if cmd == "permissions":
        if args.strip():
            try:
                new_mode = PermissionMode(args.strip())
                runtime.permission_policy.mode = new_mode
                return f"Permission mode set to: {new_mode.value}"
            except ValueError:
                valid = ", ".join(m.value for m in PermissionMode)
                return f"Invalid mode. Valid modes: {valid}"
        return f"Current permission mode: {runtime.permission_policy.mode.value}"

    # --- Config ---
    if cmd == "config":
        return _format_config(config)

    # --- MCP ---
    if cmd == "mcp":
        return handle_mcp_command(args)

    # --- Plugins ---
    if cmd == "plugins":
        return handle_plugins_command(args, plugin_manager)

    # --- Skills ---
    if cmd == "skills":
        return handle_skills_command(args)

    # --- Agents ---
    if cmd == "agents":
        return handle_agents_command(args)

    # --- Memory ---
    if cmd == "memory":
        return _handle_memory_command(args)

    # --- Init ---
    if cmd == "init":
        return _handle_init_command()

    # --- Doctor ---
    if cmd == "doctor":
        return _run_doctor_checks()

    # --- Resume ---
    if cmd == "resume":
        return _handle_resume_in_repl(args, session, runtime)

    # --- Version ---
    if cmd == "version":
        return f"axion-code {__version__}"

    # --- Sandbox ---
    if cmd == "sandbox":
        status = detect_sandbox()
        return (
            f"Sandbox status:\n"
            f"  Available: {status.available}\n"
            f"  Enabled: {status.enabled}\n"
            f"  Platform: {status.platform}\n"
            f"  Details: {status.details}"
        )

    # --- Diff ---
    if cmd == "diff":
        return _handle_diff_command(args, session)

    # --- Export ---
    if cmd == "export":
        return _handle_export_command(args, session)

    # --- Session ---
    if cmd == "session":
        return _handle_session_command(args, session)

    # --- Plan mode ---
    if cmd == "plan":
        return _handle_plan_command(args, runtime, session)

    return f"Command /{cmd} recognized but has no handler yet."


def _format_status(runtime: ConversationRuntime, session: Session) -> str:
    """Format a full status report."""
    lines: list[str] = []
    lines.append("Session Status")
    lines.append(f"  Session ID: {session.session_id}")
    lines.append(f"  Model: {runtime.model}")
    lines.append(f"  Permission mode: {runtime.permission_policy.mode.value}")
    lines.append(f"  Messages: {session.message_count()}")
    lines.append(f"  Turns: {runtime.usage_tracker.turn_count}")

    tokens_est = estimate_session_tokens(session)
    lines.append(f"  Estimated tokens: {tokens_est:,}")

    if runtime.usage_tracker.total.total_tokens() > 0:
        cost = runtime.usage_tracker.total.estimate_cost_usd()
        lines.append(f"  Total tokens used: {runtime.usage_tracker.total.total_tokens():,}")
        lines.append(f"  Estimated cost: {format_usd(cost.total_cost_usd())}")

    branch = _git_branch()
    if branch:
        lines.append(f"  Git branch: {branch}")

    git_st = _git_status_short()
    if git_st:
        lines.append(f"  Git status: {git_st}")

    lines.append(f"  Working directory: {Path.cwd()}")

    if session.compaction:
        lines.append(
            f"  Compactions: {session.compaction.count} "
            f"(removed {session.compaction.removed_message_count} messages)"
        )

    if session.fork:
        lines.append(f"  Forked from: {session.fork.parent_session_id}")

    return "\n".join(lines)


def _format_config(config: RuntimeConfig) -> str:
    """Format the merged configuration for display."""
    lines: list[str] = []
    lines.append("Configuration")
    lines.append("")

    # Sources
    lines.append("  Sources loaded:")
    if config.loaded_entries:
        for entry in config.loaded_entries:
            lines.append(f"    [{entry.source.value}] {entry.path}")
    else:
        lines.append("    (none)")

    # Features
    fc = config.feature_config
    lines.append("")
    lines.append("  Features:")
    if fc.model:
        lines.append(f"    Model: {fc.model}")
    if fc.permission_mode:
        lines.append(f"    Permission mode: {fc.permission_mode}")
    if fc.mcp:
        lines.append(f"    MCP servers: {len(fc.mcp)}")
    if fc.plugins:
        lines.append(f"    Plugins configured: {len(fc.plugins)}")
    if fc.hooks.pre_tool_use or fc.hooks.post_tool_use:
        hook_count = len(fc.hooks.pre_tool_use) + len(fc.hooks.post_tool_use)
        lines.append(f"    Hooks: {hook_count}")

    # Merged JSON (compact)
    lines.append("")
    lines.append("  Merged config:")
    if config.merged:
        formatted = json.dumps(config.merged, indent=4)
        for line in formatted.splitlines()[:30]:
            lines.append(f"    {line}")
        if len(formatted.splitlines()) > 30:
            lines.append("    ... (truncated)")
    else:
        lines.append("    {}")

    return "\n".join(lines)


def _handle_memory_command(args: str) -> str:
    """Handle /memory command for managing CLAUDE.md."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "show"

    claude_md = Path.cwd() / "CLAUDE.md"

    if action == "show":
        if not claude_md.exists():
            return "No CLAUDE.md found in current directory."
        content = claude_md.read_text(encoding="utf-8")
        if len(content) > 2000:
            content = content[:2000] + "\n... (truncated)"
        return f"CLAUDE.md contents:\n\n{content}"

    if action == "add":
        if len(parts) < 2:
            return "Usage: /memory add <text to append>"
        text_to_add = parts[1]
        with open(claude_md, "a", encoding="utf-8") as f:
            f.write(f"\n{text_to_add}\n")
        return "Appended to CLAUDE.md."

    if action == "edit":
        return "Use /memory show to view, then edit CLAUDE.md directly."

    return "Usage: /memory [show|add <text>|edit]"


def _handle_init_command() -> str:
    """Handle /init command to create CLAUDE.md."""
    claude_md = Path.cwd() / "CLAUDE.md"
    if claude_md.exists():
        return "CLAUDE.md already exists."
    claude_md.write_text(
        "# CLAUDE.md\n\n"
        "This file provides guidance to Claude Code when working with this codebase.\n\n"
        "## Project overview\n\n"
        "<!-- Describe your project here -->\n\n"
        "## Build & test\n\n"
        "<!-- Add build and test commands -->\n",
        encoding="utf-8",
    )
    return "Created CLAUDE.md."


def _handle_resume_in_repl(args: str, session: Session, runtime: ConversationRuntime) -> str:
    """Handle /resume inside the REPL."""
    identifier = args.strip() or "latest"
    path = _resolve_session(identifier)
    if path is None:
        return f"No session found for: {identifier}"

    try:
        loaded = Session.load(path)
    except Exception as exc:
        return f"Failed to load session: {exc}"

    # Replace current session state
    session.session_id = loaded.session_id
    session.created_at_ms = loaded.created_at_ms
    session.updated_at_ms = loaded.updated_at_ms
    session.messages = loaded.messages
    session.compaction = loaded.compaction
    session.fork = loaded.fork

    # Rebuild usage tracker from loaded messages
    runtime.usage_tracker = UsageTracker.from_session(session)

    return (
        f"Resumed session {session.session_id} "
        f"({session.message_count()} messages, "
        f"{runtime.usage_tracker.turn_count} turns)"
    )


def _handle_plan_command(args: str, runtime: ConversationRuntime, session: Session) -> str:
    """Handle /plan [task] | /plan execute | /plan exit."""
    from axion.runtime.plan_mode import PLAN_MODE_SYSTEM_PROMPT

    subcommand = args.strip().lower().split()[0] if args.strip() else ""
    task = args.strip()

    # /plan exit — leave plan mode
    if subcommand in ("exit", "cancel", "stop"):
        if not runtime.plan_mode_active:
            return "Not in plan mode."
        runtime.plan_mode_active = False
        # Remove the plan mode prompt addition
        if PLAN_MODE_SYSTEM_PROMPT in runtime.system_prompt:
            runtime.system_prompt = runtime.system_prompt.replace(PLAN_MODE_SYSTEM_PROMPT, "")
        return "Exited plan mode. Write tools are now available."

    # /plan execute — approve plan and exit plan mode
    if subcommand in ("execute", "run", "go", "approve", "yes"):
        if not runtime.plan_mode_active:
            return "Not in plan mode. Use /plan <task> to enter plan mode first."
        runtime.plan_mode_active = False
        if PLAN_MODE_SYSTEM_PROMPT in runtime.system_prompt:
            runtime.system_prompt = runtime.system_prompt.replace(PLAN_MODE_SYSTEM_PROMPT, "")
        return (
            "Plan approved! Exiting plan mode.\n"
            "Write tools are now available. Send your next message to start implementing."
        )

    # /plan status — check if in plan mode
    if subcommand == "status":
        if runtime.plan_mode_active:
            return "Plan mode: ACTIVE (read-only tools only)"
        return "Plan mode: inactive"

    # /plan (no args) — show help
    if not task:
        if runtime.plan_mode_active:
            return (
                "Plan mode is ACTIVE.\n"
                "  /plan exit    — Leave plan mode\n"
                "  /plan execute — Approve plan and start implementing\n"
                "  /plan status  — Check plan mode status"
            )
        return (
            "Usage: /plan <task description>\n"
            "  Enter plan mode where the AI explores and designs before coding.\n"
            "  Only read-only tools (Read, Glob, Grep, WebSearch) are allowed.\n\n"
            "  Example: /plan Add user authentication with JWT tokens\n\n"
            "  Subcommands:\n"
            "    /plan execute — Approve plan and start implementing\n"
            "    /plan exit    — Cancel and leave plan mode"
        )

    # /plan <task> — enter plan mode with a task
    if runtime.plan_mode_active:
        return "Already in plan mode. Use /plan exit first, or send your task as a message."

    runtime.plan_mode_active = True
    # Augment the system prompt with plan mode instructions
    runtime.system_prompt += PLAN_MODE_SYSTEM_PROMPT

    return (
        "📋 Plan mode ACTIVE\n"
        "  Only read-only tools allowed (Read, Glob, Grep, WebSearch).\n"
        "  Write/Edit/Bash are blocked until you approve.\n\n"
        f"  Task: {task}\n\n"
        "  Send your next message to start planning, or just say 'go'.\n"
        "  When done: /plan execute to approve, /plan exit to cancel."
    )


def _handle_diff_command(args: str, session: Session) -> str:
    """Handle /diff with syntax-highlighted output using Rich."""
    from rich.syntax import Syntax

    # Get both staged and unstaged diffs
    sections: list[str] = []
    for label, git_args in [
        ("Staged changes", ["git", "diff", "--cached"]),
        ("Unstaged changes", ["git", "diff"]),
    ]:
        try:
            result = subprocess.run(
                git_args, capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                sections.append(f"### {label}")
                diff_text = result.stdout.strip()
                if len(diff_text) > 5000:
                    diff_text = diff_text[:5000] + "\n... (truncated)"
                # Render with syntax highlighting
                syntax = Syntax(diff_text, "diff", theme="monokai", line_numbers=False)
                console.print(syntax)
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

    if not sections:
        return "No uncommitted changes."
    return ""  # Already printed via Rich


def _handle_export_command(args: str, session: Session) -> str:
    """Handle /export to save the session transcript."""
    output_name = args.strip() or f"transcript-{session.session_id}.md"
    output_path = Path.cwd() / output_name
    try:
        _export_transcript(session, output_path)
        return f"Exported transcript to: {output_path}"
    except Exception as exc:
        return f"Export failed: {exc}"


def _handle_session_command(args: str, session: Session) -> str:
    """Handle /session [list|show|fork|save] commands."""
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "show"

    if action == "show":
        return (
            f"Session ID: {session.session_id}\n"
            f"Created: {datetime.fromtimestamp(session.created_at_ms / 1000).isoformat()}\n"
            f"Updated: {datetime.fromtimestamp(session.updated_at_ms / 1000).isoformat()}\n"
            f"Messages: {session.message_count()}\n"
            f"Compactions: {session.compaction.count if session.compaction else 0}"
        )

    if action == "list":
        files = _list_sessions()
        if not files:
            return "No saved sessions."
        lines = ["Saved sessions:", ""]
        for f in files:
            mod_time = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {f.stem}  ({mod_time})")
        return "\n".join(lines)

    if action == "fork":
        from axion.runtime.session import SessionFork
        branch_name = parts[1].strip() if len(parts) > 1 else None
        old_id = session.session_id
        # Create new session ID but keep messages
        import uuid
        session.session_id = uuid.uuid4().hex[:16]
        session.fork = SessionFork(
            parent_session_id=old_id,
            branch_name=branch_name,
        )
        return f"Forked session {old_id} -> {session.session_id}"

    if action == "save":
        path = _session_path_for_id(session.session_id)
        session.save(path)
        return f"Session saved to: {path}"

    if action in ("switch", "sw"):
        target = parts[1].strip() if len(parts) > 1 else ""
        if not target:
            return "Usage: /session switch <session_id|latest>"
        path = _resolve_session(target)
        if path is None:
            return f"Session not found: {target}"
        try:
            loaded = Session.load(path)
            # Replace current session state
            session.session_id = loaded.session_id
            session.messages = loaded.messages
            session.created_at_ms = loaded.created_at_ms
            session.updated_at_ms = loaded.updated_at_ms
            session.compaction = loaded.compaction
            session.fork = loaded.fork
            # Update persistence path
            session.with_persistence_path(_session_path_for_id(loaded.session_id))
            return (
                f"Switched to session {loaded.session_id}\n"
                f"  Messages: {loaded.message_count()}\n"
                f"  Created: {datetime.fromtimestamp(loaded.created_at_ms / 1000).strftime('%Y-%m-%d %H:%M')}"
            )
        except Exception as exc:
            return f"Failed to switch session: {exc}"

    if action in ("delete", "rm"):
        target = parts[1].strip() if len(parts) > 1 else ""
        if not target:
            return "Usage: /session delete <session_id>"
        if target == session.session_id:
            return "Cannot delete the current active session."
        path = _resolve_session(target)
        if path is None:
            return f"Session not found: {target}"
        try:
            path.unlink()
            return f"Deleted session: {path.stem}"
        except Exception as exc:
            return f"Failed to delete session: {exc}"

    if action == "new":
        # Save current session first
        try:
            session.save()
        except Exception:
            pass
        old_id = session.session_id
        # Reset to a fresh session
        import uuid
        session.session_id = uuid.uuid4().hex[:16]
        session.messages.clear()
        session.compaction = None
        session.fork = None
        session.created_at_ms = int(time.time() * 1000)
        session.updated_at_ms = session.created_at_ms
        session.with_persistence_path(_session_path_for_id(session.session_id))
        return f"New session {session.session_id} (previous: {old_id})"

    return "Usage: /session [show|list|fork|save|switch|delete|new]"


def _run_doctor_checks() -> str:
    """Run health checks and return results."""
    lines: list[str] = []
    lines.append("Axion Code Doctor")
    lines.append("")

    # Python version
    py_version = sys.version.split()[0]
    py_ok = sys.version_info >= (3, 11)
    lines.append(f"  Python: {py_version} {'OK' if py_ok else 'NEEDS 3.11+'}")

    # API key
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    lines.append(f"  ANTHROPIC_API_KEY: {'SET' if has_key else 'NOT SET'}")

    # OAuth credentials
    oauth_creds = load_oauth_credentials("anthropic")
    if oauth_creds:
        expired_str = " (expired)" if oauth_creds.is_expired() else " (valid)"
        lines.append(f"  OAuth credentials: FOUND{expired_str}")
    else:
        lines.append("  OAuth credentials: NOT FOUND")

    # Dependencies
    deps = ["httpx", "rich", "click", "prompt_toolkit"]
    for dep in deps:
        try:
            __import__(dep)
            lines.append(f"  {dep}: OK")
        except ImportError:
            lines.append(f"  {dep}: MISSING")

    # Git
    try:
        result = subprocess.run(
            ["git", "--version"], capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            lines.append(f"  git: {result.stdout.strip()}")
        else:
            lines.append("  git: NOT FOUND")
    except (subprocess.SubprocessError, FileNotFoundError):
        lines.append("  git: NOT FOUND")

    # Sandbox
    sandbox = detect_sandbox()
    lines.append(f"  Sandbox: {'available' if sandbox.available else 'not available'} ({sandbox.details})")

    # Config files
    loader = ConfigLoader()
    config = loader.load()
    lines.append(f"  Config sources loaded: {len(config.loaded_entries)}")

    # Session directory
    sd = Path.cwd() / SESSION_DIR
    sessions_count = len(list(sd.glob("*.jsonl"))) if sd.exists() else 0
    lines.append(f"  Sessions directory: {sd} ({sessions_count} sessions)")

    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# REPL loop
# ---------------------------------------------------------------------------

async def run_repl(
    model: str,
    permission_mode: str,
    resume: str | None = None,
    output_format: str = "text",
    budget: float | None = None,
) -> int:
    """Run the interactive REPL loop."""
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory

    config = _load_config()
    plugin_manager = _create_plugin_manager()

    # Create or resume session
    if resume:
        path = _resolve_session(resume)
        if path is None:
            console.print(f"[red]Session not found: {resume}[/red]")
            return 1
        try:
            session = Session.load(path)
            console.print(f"[dim]Resumed session {session.session_id} ({session.message_count()} messages)[/dim]")
        except Exception as exc:
            console.print(f"[red]Failed to load session: {exc}[/red]")
            return 1
    else:
        session = Session()

    # Set up persistence
    session_path = _session_path_for_id(session.session_id)
    session.with_persistence_path(session_path)

    # Build runtime with markdown streaming and real-time tool display
    text_buffer: list[str] = []
    repl_md_stream = MarkdownStreamState()

    def on_text_delta(text: str) -> None:
        text_buffer.append(text)
        if output_format == "json":
            return
        rendered = repl_md_stream.push(renderer, text)
        if rendered:
            console.print(Markdown(rendered), end="")

    def on_tool_use_cb(tool_name: str, tool_input: str) -> None:
        """Show tool invocation in real-time as it happens."""
        if output_format == "json":
            return
        # Flush any pending markdown before showing tool
        remaining = repl_md_stream.flush(renderer)
        if remaining:
            console.print(Markdown(remaining))
        _render_tool_use(tool_name, tool_input)

    def on_tool_result_cb(tool_name: str, output: str, is_error: bool) -> None:
        """Show tool result in real-time as it completes."""
        if output_format == "json":
            return
        _render_tool_result(tool_name, output, is_error)

    thinking_started = [False]  # mutable flag for closure

    def on_thinking_cb(thinking_text: str) -> None:
        """Show collapsed thinking indicator."""
        if output_format == "json":
            return
        if not thinking_started[0]:
            thinking_started[0] = True
            console.print("[dim italic]💭 Thinking...[/dim italic]")
        # Don't show the actual thinking text — just the indicator

    runtime, provider = _build_runtime(
        model=model,
        permission_mode=permission_mode,
        session=session,
        config=config,
        on_text_delta=on_text_delta,
        on_tool_use=on_tool_use_cb,
        on_tool_result=on_tool_result_cb,
    )
    runtime.on_thinking = on_thinking_cb
    if budget is not None:
        runtime.cost_budget_usd = budget

    # Restore usage tracker from resumed session
    if resume:
        runtime.usage_tracker = UsageTracker.from_session(session)

    # Welcome banner
    if output_format != "json":
        renderer.render_welcome(__version__, runtime.model)
        perm_display = runtime.permission_policy.mode.value
        console.print(f"[dim]Permissions: {perm_display} | Session: {session.session_id[:8]}...[/dim]")
        branch = _git_branch()
        if branch:
            console.print(f"[dim]Git branch: {branch}[/dim]")
        console.print()

    # REPL history
    history_dir = Path.home() / ".axion"
    history_dir.mkdir(parents=True, exist_ok=True)
    history_path = history_dir / "repl_history"
    prompt_session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path))
    )

    _turn_interrupted = False

    try:
        while True:
            # Read input
            try:
                prompt_text = "axion[plan]> " if runtime.plan_mode_active else "axion> "
                user_input = await prompt_session.prompt_async(prompt_text)
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye![/dim]")
                break

            user_input = user_input.strip()
            if not user_input:
                continue

            # Catch common mistake: typing a command without the /
            _command_words = {
                "help", "quit", "exit", "clear", "cost", "status", "model",
                "compact", "config", "diff", "export", "doctor", "version",
                "resume", "login", "logout", "session", "plugins", "skills",
                "agents", "mcp", "memory", "models", "permissions", "sandbox",
            }
            first_word = user_input.split()[0].lower()
            if first_word in _command_words:
                console.print(
                    f"[yellow]Did you mean [bold]/{user_input}[/bold]? "
                    f"Commands start with /[/yellow]"
                )
                continue

            # Handle slash commands
            if user_input.startswith("/"):
                response = await _handle_slash_command(
                    user_input, runtime, session, plugin_manager, config
                )
                if response is None:
                    # Exit signal
                    console.print("[dim]Goodbye![/dim]")
                    break
                console.print(f"[dim]{response}[/dim]")

                # Persist session after commands that mutate state
                try:
                    session.save()
                except Exception:
                    pass
                continue

            # Send to model
            text_buffer.clear()
            _turn_interrupted = False
            thinking_started[0] = False

            # Spinner to show while waiting for first response
            from axion.cli.render import Spinner as AxionSpinner
            spinner = AxionSpinner()
            spinner_active = True

            _original_text_cb = runtime.on_text_delta
            _original_tool_cb = runtime.on_tool_use

            def _stop_spinner() -> None:
                nonlocal spinner_active
                if spinner_active:
                    spinner.stop()
                    spinner_active = False

            def _text_with_spinner(text: str) -> None:
                _stop_spinner()
                if _original_text_cb:
                    _original_text_cb(text)

            def _tool_with_spinner(name: str, inp: str) -> None:
                _stop_spinner()
                if _original_tool_cb:
                    _original_tool_cb(name, inp)

            runtime.on_text_delta = _text_with_spinner
            runtime.on_tool_use = _tool_with_spinner
            # Wire spinner stop into permission prompter so it clears before [y/N] shows
            if runtime.permission_prompter and hasattr(runtime.permission_prompter, '_stop_spinner_fn'):
                runtime.permission_prompter._stop_spinner_fn = _stop_spinner

            try:
                if output_format != "json":
                    console.print()  # Blank line before response
                    spinner.start("Thinking...")

                summary = await runtime.run_turn(user_input)
                _stop_spinner()

                # Flush remaining markdown
                if output_format != "json":
                    remaining = repl_md_stream.flush(renderer)
                    if remaining:
                        console.print(Markdown(remaining))

                if output_format == "json":
                    json_out = _build_json_output(summary, runtime.model)
                    click.echo(json.dumps(json_out))
                else:
                    console.print()  # Newline after streaming
                    # Tool use/results are now shown in real-time via callbacks

                    # Cost line
                    if summary.usage.total_tokens() > 0:
                        cost = summary.usage.estimate_cost_usd()
                        console.print(
                            f"[dim]Tokens: {summary.usage.total_tokens():,} | "
                            f"Cost: {format_usd(cost.total_cost_usd())} | "
                            f"Turn {runtime.usage_tracker.turn_count}[/dim]"
                        )

            except KeyboardInterrupt:
                _stop_spinner()
                _turn_interrupted = True
                console.print("\n[yellow]Interrupted[/yellow]")
                repl_md_stream._pending = ""
                repl_md_stream._in_code_fence = False
            except Exception as exc:
                _stop_spinner()
                repl_md_stream._pending = ""
                repl_md_stream._in_code_fence = False
                error_msg = str(exc)
                if output_format == "json":
                    click.echo(json.dumps({"error": error_msg}))
                elif "context window" in error_msg.lower() or "too many tokens" in error_msg.lower():
                    renderer.render_context_window_error(
                        model=runtime.model,
                        estimated_tokens=estimate_session_tokens(session),
                        context_window=200_000,
                        session_id=session.session_id,
                    )
                    console.print("[dim]Try /compact to reduce history or /clear to start fresh.[/dim]")
                elif "api key" in error_msg.lower() or "credentials" in error_msg.lower():
                    console.print(f"[red]Authentication error: {error_msg}[/red]")
                    console.print("[dim]Check your ANTHROPIC_API_KEY or run /login[/dim]")
                elif "timeout" in error_msg.lower() or "connect" in error_msg.lower():
                    console.print(f"[yellow]Connection error: {error_msg}[/yellow]")
                    console.print("[dim]Check your internet connection and try again.[/dim]")
                else:
                    console.print(f"\n[red]Error: {error_msg}[/red]")
                logger.exception("Error during turn")

            finally:
                # Restore original callbacks
                runtime.on_text_delta = _original_text_cb
                runtime.on_tool_use = _original_tool_cb

            # Persist session after each turn
            try:
                session.save()
            except Exception:
                logger.debug("Failed to persist session", exc_info=True)

    finally:
        await provider.close()

    return 0


# ---------------------------------------------------------------------------
# OAuth login/logout
# ---------------------------------------------------------------------------

async def _run_login(provider_name: str = "anthropic") -> int:
    """Log in by entering an API key (saved permanently) or via OAuth."""
    console.print("[bold]Axion Code Login[/bold]\n")

    # Check for existing saved key
    key_path = Path.home() / ".axion" / "credentials" / f"{provider_name}.key"
    if key_path.exists():
        saved_key = key_path.read_text(encoding="utf-8").strip()
        if saved_key:
            masked = saved_key[:8] + "..." + saved_key[-4:]
            console.print(f"[green]Already logged in.[/green] Key: {masked}")
            console.print("[dim]Use 'axion logout' to clear credentials.[/dim]")
            return 0

    # Check env var
    env_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "xai": "XAI_API_KEY",
    }
    env_var = env_vars.get(provider_name, "ANTHROPIC_API_KEY")
    existing_env = os.environ.get(env_var)
    if existing_env:
        console.print(f"[green]{env_var} is already set in your environment.[/green]")
        console.print("[dim]Want to save it permanently? Enter 'save' below, or enter a different key.[/dim]\n")

    # Provider-specific info
    provider_info = {
        "anthropic": {
            "display": "Anthropic (Claude)",
            "url": "https://console.anthropic.com/settings/keys",
            "prefix": "sk-ant-",
            "models": "opus, sonnet, haiku",
        },
        "openai": {
            "display": "OpenAI (GPT)",
            "url": "https://platform.openai.com/api-keys",
            "prefix": "sk-",
            "models": "gpt-4o, o1, o3",
        },
        "xai": {
            "display": "xAI (Grok)",
            "url": "https://console.x.ai",
            "prefix": "xai-",
            "models": "grok-2",
        },
    }
    info = provider_info.get(provider_name, provider_info["anthropic"])

    # Prompt for API key
    console.print(f"Provider: [bold]{info['display']}[/bold]")
    console.print(f"Models: [dim]{info['models']}[/dim]")
    console.print()
    console.print("Enter your API key (or 'save' to save the current env key):")
    console.print(f"  Get one at: [link]{info['url']}[/link]")
    console.print()

    try:
        answer = console.input("[cyan]API key: [/cyan]").strip()
    except (EOFError, KeyboardInterrupt):
        console.print("\n[dim]Cancelled.[/dim]")
        return 1

    if not answer:
        console.print("[yellow]No key entered.[/yellow]")
        return 1

    # Handle 'save' — persist the env var key
    if answer.lower() == "save" and existing_env:
        answer = existing_env

    # Save the key permanently
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(answer, encoding="utf-8")
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass

    # Also set it in the current process so it works immediately
    os.environ[env_var] = answer

    masked = answer[:8] + "..." + answer[-4:]
    console.print(f"\n[green]Key saved![/green] ({masked})")
    console.print(f"Stored at: [dim]{key_path}[/dim]")

    # Show how to use it
    if provider_name == "anthropic":
        console.print("\n[bold]You're ready to go![/bold] Run [cyan]axion[/cyan] to start.")
    elif provider_name == "openai":
        console.print("\n[bold]You're ready to go![/bold] Run [cyan]axion -m gpt-4o[/cyan] to start.")
    elif provider_name == "xai":
        console.print("\n[bold]You're ready to go![/bold] Run [cyan]axion -m grok-2[/cyan] to start.")
    return 0


def _run_logout(provider_name: str = "anthropic") -> int:
    """Clear all stored credentials (API key + OAuth)."""
    console.print("[bold]Axion Code Logout[/bold]\n")
    cleared = False

    # Clear saved API key
    key_path = Path.home() / ".axion" / "credentials" / f"{provider_name}.key"
    if key_path.exists():
        key_path.unlink()
        console.print(f"[green]Removed saved API key: {key_path}[/green]")
        cleared = True

    # Clear OAuth credentials
    existing = load_oauth_credentials(provider_name)
    if existing is not None:
        clear_oauth_credentials(provider_name)
        console.print("[green]Cleared OAuth credentials.[/green]")
        cleared = True

    # Clear env var for this process
    env_vars = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "xai": "XAI_API_KEY"}
    env_var = env_vars.get(provider_name)
    if env_var and env_var in os.environ:
        del os.environ[env_var]
        console.print(f"[green]Cleared {env_var} from current session.[/green]")
        cleared = True

    if not cleared:
        console.print("[dim]No stored credentials found.[/dim]")

    return 0


# ---------------------------------------------------------------------------
# Click CLI definition
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.option("--model", "-m", default=DEFAULT_MODEL, help="Model to use")
@click.option(
    "--permission-mode",
    type=click.Choice(["allow", "read-only", "workspace-write", "danger-full-access", "prompt"]),
    default="allow",
    help="Permission mode for tool execution",
)
@click.option("--prompt", "-p", default=None, help="One-shot prompt (non-interactive)")
@click.option("--version", "-v", is_flag=True, help="Show version")
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format (text or json)",
)
@click.option("--resume", "-r", default=None, help="Resume session (ID, path, or 'latest')")
@click.option("--verbose", is_flag=True, help="Enable verbose logging")
@click.option("--system-prompt", "system_prompt_file", default=None, type=click.Path(exists=True),
              help="Path to a custom system prompt file")
@click.option("--budget", default=None, type=float,
              help="Max cost budget in USD for this session (e.g. --budget 1.00)")
@click.pass_context
def cli(
    ctx: click.Context,
    model: str,
    permission_mode: str,
    prompt: str | None,
    version: bool,
    output_format: str,
    resume: str | None,
    verbose: bool,
    system_prompt_file: str | None,
    budget: float | None,
) -> None:
    """Axion Code - Python CLI agent harness.

    Interactive AI coding assistant powered by Claude.

    Run without arguments for interactive REPL mode, or pass --prompt/-p for
    one-shot execution. Use subcommands for specific operations.
    """
    if verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING)

    if version:
        click.echo(f"axion-code {__version__}")
        return

    # Store shared state on context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["model"] = model
    ctx.obj["permission_mode"] = permission_mode
    ctx.obj["output_format"] = output_format
    ctx.obj["system_prompt_file"] = system_prompt_file

    if ctx.invoked_subcommand is not None:
        return

    try:
        if prompt:
            exit_code = asyncio.run(run_one_shot(prompt, model, permission_mode, output_format))
        else:
            exit_code = asyncio.run(run_repl(model, permission_mode, resume, output_format, budget))
    except Exception as exc:
        error_msg = str(exc)
        if "credentials" in error_msg.lower() or "api key" in error_msg.lower():
            console.print()
            console.print("[bold red]No API key configured.[/bold red]")
            console.print()
            console.print("Quick setup:")
            console.print("  [cyan]axion login[/cyan]                          (paste your API key, saved permanently)")
            console.print()
            console.print("Or set an environment variable:")
            console.print("  [cyan]$env:ANTHROPIC_API_KEY=\"sk-ant-...\"[/cyan]  (PowerShell)")
            console.print("  [cyan]export ANTHROPIC_API_KEY=sk-ant-...[/cyan]   (Linux/Mac)")
            console.print()
            console.print("Or use a local model with Ollama (free, no key needed):")
            console.print("  [cyan]ollama pull llama3.1[/cyan]")
            console.print("  [cyan]axion -m llama3.1[/cyan]")
            console.print()
            console.print("Run [bold]axion doctor[/bold] to check your setup.")
            exit_code = 1
        else:
            console.print(f"[red]Error: {error_msg}[/red]")
            exit_code = 1

    sys.exit(exit_code)


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current environment status."""
    console.print(f"[bold]Axion Code[/bold] v{__version__}")
    console.print(f"Working directory: {Path.cwd()}")

    model = ctx.obj.get("model", DEFAULT_MODEL) if ctx.obj else DEFAULT_MODEL
    console.print(f"Model: [cyan]{resolve_model_alias(model)}[/cyan]")

    branch = _git_branch()
    if branch:
        console.print(f"Git branch: {branch}")

    git_st = _git_status_short()
    if git_st:
        console.print(f"Git status: {git_st}")

    config = _load_config()
    console.print(f"Config sources: {len(config.loaded_entries)}")

    # API key status
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    oauth = load_oauth_credentials("anthropic")
    if has_key:
        console.print("Auth: [green]API key set[/green]")
    elif oauth and not oauth.is_expired():
        console.print("Auth: [green]OAuth (valid)[/green]")
    else:
        console.print("Auth: [yellow]Not configured[/yellow]")

    # Sandbox
    sandbox = detect_sandbox()
    console.print(f"Sandbox: {'available' if sandbox.available else 'not available'} ({sandbox.details})")

    # Sessions
    sessions = _list_sessions()
    console.print(f"Saved sessions: {len(sessions)}")


@cli.command()
def sandbox() -> None:
    """Show sandbox status and capabilities."""
    status = detect_sandbox()
    console.print("[bold]Sandbox Status[/bold]\n")
    console.print(f"  Available: {'yes' if status.available else 'no'}")
    console.print(f"  Enabled: {'yes' if status.enabled else 'no'}")
    console.print(f"  Platform: {status.platform}")
    console.print(f"  Details: {status.details}")


@cli.command()
@click.argument("args", nargs=-1)
def agents(args: tuple[str, ...]) -> None:
    """List and manage available agents."""
    args_str = " ".join(args)
    result = handle_agents_command(args_str)
    console.print(result)


@cli.command()
@click.argument("args", nargs=-1)
def mcp(args: tuple[str, ...]) -> None:
    """Manage MCP (Model Context Protocol) servers."""
    args_str = " ".join(args)
    result = handle_mcp_command(args_str)
    console.print(result)


@cli.command()
@click.argument("args", nargs=-1)
def skills(args: tuple[str, ...]) -> None:
    """List available skills."""
    args_str = " ".join(args)
    result = handle_skills_command(args_str)
    console.print(result)


@cli.command()
@click.argument("args", nargs=-1)
def plugins(args: tuple[str, ...]) -> None:
    """Manage plugins."""
    args_str = " ".join(args)
    manager = _create_plugin_manager()
    result = handle_plugins_command(args_str, manager)
    console.print(result)


@cli.command(name="system-prompt")
@click.option("--file", "-f", "file_path", default=None, type=click.Path(exists=True),
              help="Load system prompt from file")
@click.pass_context
def system_prompt_cmd(ctx: click.Context, file_path: str | None) -> None:
    """Show or set the system prompt."""
    if file_path:
        content = Path(file_path).read_text(encoding="utf-8")
        console.print(f"[dim]System prompt from {file_path}:[/dim]\n")
        console.print(Markdown(content))
    else:
        builder = SystemPromptBuilder.for_cwd()
        prompt_text = builder.build()
        console.print("[bold]Current system prompt:[/bold]\n")
        # Truncate very long prompts for display
        if len(prompt_text) > 5000:
            console.print(prompt_text[:5000])
            console.print(f"\n[dim]... ({len(prompt_text)} chars total, truncated)[/dim]")
        else:
            console.print(prompt_text)


@cli.command()
@click.option("--provider", default="anthropic", help="OAuth provider")
def login(provider: str) -> None:
    """Log in via OAuth or check API key status."""
    exit_code = asyncio.run(_run_login(provider))
    sys.exit(exit_code)


@cli.command()
@click.option("--provider", default="anthropic", help="OAuth provider")
def logout(provider: str) -> None:
    """Log out and clear stored credentials."""
    exit_code = _run_logout(provider)
    sys.exit(exit_code)


@cli.command()
def doctor() -> None:
    """Run health checks on the environment."""
    result = _run_doctor_checks()
    console.print(result)


@cli.command()
def init() -> None:
    """Initialize a new project with CLAUDE.md."""
    result = _handle_init_command()
    console.print(result)


@cli.command(name="version")
def version_cmd() -> None:
    """Show version information."""
    click.echo(f"axion-code {__version__}")
    click.echo(f"Python {sys.version.split()[0]}")
    click.echo(f"Platform: {sys.platform}")


@cli.command()
@click.argument("session_id", default="latest")
@click.option("--model", "-m", default=DEFAULT_MODEL, help="Model to use")
@click.option(
    "--permission-mode",
    type=click.Choice(["allow", "read-only", "workspace-write", "danger-full-access", "prompt"]),
    default="allow",
)
def resume(session_id: str, model: str, permission_mode: str) -> None:
    """Resume a previous session.

    SESSION_ID can be a full session ID, partial ID, file path, or 'latest'.
    """
    exit_code = asyncio.run(run_repl(model, permission_mode, resume=session_id))
    sys.exit(exit_code)


@cli.command()
@click.argument("session_id", default="latest")
@click.option("--output", "-o", default=None, help="Output file path")
def export(session_id: str, output: str | None) -> None:
    """Export a session transcript to markdown.

    SESSION_ID can be a session ID, partial ID, file path, or 'latest'.
    """
    path = _resolve_session(session_id)
    if path is None:
        console.print(f"[red]Session not found: {session_id}[/red]")
        sys.exit(1)

    try:
        session = Session.load(path)
    except Exception as exc:
        console.print(f"[red]Failed to load session: {exc}[/red]")
        sys.exit(1)

    output_path = Path(output) if output else Path.cwd() / f"transcript-{session.session_id}.md"
    _export_transcript(session, output_path)
    console.print(f"[green]Exported to: {output_path}[/green]")


@cli.command()
def config() -> None:
    """Show merged configuration from all sources."""
    cfg = _load_config()
    result = _format_config(cfg)
    console.print(result)


@cli.command(name="session")
@click.argument("action", default="list")
@click.argument("args", nargs=-1)
def session_cmd(action: str, args: tuple[str, ...]) -> None:
    """Manage sessions (list, show, delete).

    \b
    Actions:
      list    - List saved sessions
      show    - Show session details
      delete  - Delete a session
    """
    if action == "list":
        files = _list_sessions()
        if not files:
            console.print("[dim]No saved sessions.[/dim]")
            return
        console.print("[bold]Saved sessions:[/bold]\n")
        for f in files:
            mod_time = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            size_kb = f.stat().st_size / 1024
            console.print(f"  {f.stem}  [dim]{mod_time}  ({size_kb:.1f} KB)[/dim]")

    elif action == "show":
        if not args:
            console.print("[yellow]Usage: axion session show <session_id>[/yellow]")
            return
        path = _resolve_session(args[0])
        if path is None:
            console.print(f"[red]Session not found: {args[0]}[/red]")
            return
        try:
            session = Session.load(path)
            console.print(f"[bold]Session: {session.session_id}[/bold]")
            console.print(f"  Created: {datetime.fromtimestamp(session.created_at_ms / 1000).isoformat()}")
            console.print(f"  Updated: {datetime.fromtimestamp(session.updated_at_ms / 1000).isoformat()}")
            console.print(f"  Messages: {session.message_count()}")
            if session.compaction:
                console.print(f"  Compactions: {session.compaction.count}")
            if session.fork:
                console.print(f"  Forked from: {session.fork.parent_session_id}")

            # Show message summary
            console.print("\n[bold]Messages:[/bold]")
            for i, msg in enumerate(session.messages):
                role = msg.role.value.upper()
                block_types = [type(b).__name__ for b in msg.blocks]
                preview = ""
                for b in msg.blocks:
                    if isinstance(b, TextBlock):
                        preview = b.text[:80].replace("\n", " ")
                        if len(b.text) > 80:
                            preview += "..."
                        break
                console.print(f"  [{i}] {role} ({', '.join(block_types)}): {preview}")
        except Exception as exc:
            console.print(f"[red]Failed to load session: {exc}[/red]")

    elif action == "delete":
        if not args:
            console.print("[yellow]Usage: axion session delete <session_id>[/yellow]")
            return
        path = _resolve_session(args[0])
        if path is None:
            console.print(f"[red]Session not found: {args[0]}[/red]")
            return
        try:
            path.unlink()
            console.print(f"[green]Deleted session: {path.stem}[/green]")
        except Exception as exc:
            console.print(f"[red]Failed to delete: {exc}[/red]")

    else:
        console.print(f"[yellow]Unknown action: {action}. Use: list, show, delete[/yellow]")


@cli.command(name="prompt")
@click.argument("prompt_text")
@click.option("--model", "-m", default=DEFAULT_MODEL)
@click.option(
    "--output-format",
    type=click.Choice(["text", "json"]),
    default="text",
)
def prompt_cmd(prompt_text: str, model: str, output_format: str) -> None:
    """Send a one-shot prompt."""
    exit_code = asyncio.run(run_one_shot(prompt_text, model, "allow", output_format))
    sys.exit(exit_code)


@cli.command()
def tools() -> None:
    """List all available tools."""
    registry = get_tool_registry()
    console.print("[bold]Available tools:[/bold]\n")
    for tool_def in registry.all_tools():
        spec = tool_def.spec
        perm = spec.required_permission
        console.print(f"  [bold]{spec.name}[/bold] [{tool_def.source}] (requires: {perm})")
        console.print(f"    {spec.description[:100]}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Main entry point."""
    cli()


if __name__ == "__main__":
    main()
