"""Rich-based terminal rendering: markdown, syntax highlighting, spinners.

Maps to: rust/crates/rusty-claude-cli/src/render.rs
"""

from __future__ import annotations

import enum
import io
import json
import re
import sys
import time
import threading
from dataclasses import dataclass, field
from typing import Any, TextIO

from rich.console import Console
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.text import Text
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table


# ---------------------------------------------------------------------------
# Constants (matching Rust render.rs)
# ---------------------------------------------------------------------------

READ_DISPLAY_MAX_LINES = 80
READ_DISPLAY_MAX_CHARS = 6_000
TOOL_OUTPUT_DISPLAY_MAX_LINES = 60
TOOL_OUTPUT_DISPLAY_MAX_CHARS = 4_000

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
SPINNER_INTERVAL_MS = 80


# ---------------------------------------------------------------------------
# Color themes
# ---------------------------------------------------------------------------

class ColorTheme(enum.Enum):
    DEFAULT = "default"
    DARK = "dark"
    LIGHT = "light"


CLAW_THEME = Theme({
    "axion.prompt": "bold cyan",
    "axion.assistant": "white",
    "axion.tool_name": "bold cyan",
    "axion.tool_border": "dim",
    "axion.tool_input": "dim",
    "axion.tool_output": "green",
    "axion.tool_success": "bold green",
    "axion.tool_error": "bold red",
    "axion.error": "bold red",
    "axion.warning": "yellow",
    "axion.info": "dim",
    "axion.cost": "dim cyan",
    "axion.status": "dim",
    "axion.heading": "bold cyan",
    "axion.code": "green",
    "axion.link": "blue underline",
    "axion.thinking": "dim italic",
})


# ---------------------------------------------------------------------------
# Spinner (matching Rust 10-frame braille spinner)
# ---------------------------------------------------------------------------

class Spinner:
    """Animated braille spinner for progress indication.

    Maps to: rust/crates/rusty-claude-cli/src/render.rs::Spinner
    """

    def __init__(self, out: TextIO | None = None) -> None:
        self._out = out or sys.stderr
        self._frame = 0
        self._running = False
        self._thread: threading.Thread | None = None
        self._label = ""
        self._lock = threading.Lock()

    def start(self, label: str = "Thinking...") -> None:
        """Start the spinner animation."""
        self._label = label
        self._running = True
        self._thread = threading.Thread(target=self._animate, daemon=True)
        self._thread.start()

    def stop(self, final_label: str | None = None, success: bool = True) -> None:
        """Stop the spinner and show final status."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        # Clear the spinner line
        self._out.write("\r\033[K")
        if final_label:
            icon = "✔" if success else "✘"
            color = "\033[32m" if success else "\033[31m"
            self._out.write(f"{color}{icon}\033[0m {final_label}\n")
        self._out.flush()

    def finish(self, label: str = "Done") -> None:
        """Stop with success indicator."""
        self.stop(label, success=True)

    def fail(self, label: str = "Failed") -> None:
        """Stop with failure indicator."""
        self.stop(label, success=False)

    def _animate(self) -> None:
        while self._running:
            with self._lock:
                frame = SPINNER_FRAMES[self._frame % len(SPINNER_FRAMES)]
                self._frame += 1
            self._out.write(f"\r\033[36m{frame}\033[0m {self._label}")
            self._out.flush()
            time.sleep(SPINNER_INTERVAL_MS / 1000)


# ---------------------------------------------------------------------------
# Markdown stream state (for incremental rendering)
# ---------------------------------------------------------------------------

class MarkdownStreamState:
    """Buffers incomplete markdown for safe streaming render.

    Maps to: rust/crates/rusty-claude-cli/src/render.rs::MarkdownStreamState
    """

    def __init__(self) -> None:
        self._pending = ""
        self._in_code_fence = False

    def push(self, renderer: TerminalRenderer, delta: str) -> str | None:
        """Accumulate delta text and render when safe.

        Returns rendered text if a safe boundary was found, None otherwise.
        """
        self._pending += delta

        boundary = self._find_safe_boundary()
        if boundary is None:
            return None

        ready = self._pending[:boundary]
        self._pending = self._pending[boundary:]

        if ready.strip():
            return ready
        return None

    def flush(self, renderer: TerminalRenderer) -> str | None:
        """Render any remaining pending text."""
        if not self._pending.strip():
            self._pending = ""
            return None
        result = self._pending
        self._pending = ""
        return result

    def _find_safe_boundary(self) -> int | None:
        """Find a safe point to split the pending text for rendering.

        Only splits outside code fences, at blank lines or code block ends.
        """
        in_fence = self._in_code_fence
        last_safe = None

        lines = self._pending.split("\n")
        pos = 0

        for i, line in enumerate(lines):
            stripped = line.strip()
            # Check for code fence toggling
            if stripped.startswith("```") or stripped.startswith("~~~"):
                in_fence = not in_fence
                if not in_fence:
                    # End of code block — safe boundary after this line
                    end_pos = pos + len(line) + 1  # +1 for newline
                    if end_pos <= len(self._pending):
                        last_safe = end_pos

            if not in_fence and stripped == "" and i > 0:
                # Blank line outside fence — safe boundary
                end_pos = pos + len(line) + 1
                if end_pos <= len(self._pending):
                    last_safe = end_pos

            pos += len(line) + 1

        # Update fence state for rendered portion
        if last_safe is not None:
            rendered = self._pending[:last_safe]
            for line in rendered.split("\n"):
                stripped = line.strip()
                if stripped.startswith("```") or stripped.startswith("~~~"):
                    self._in_code_fence = not self._in_code_fence

        return last_safe


# ---------------------------------------------------------------------------
# Tool display formatting
# ---------------------------------------------------------------------------

def format_tool_call_start(tool_name: str, tool_input: str) -> str:
    """Format a tool invocation with box-drawing characters.

    Maps to: rust/crates/rusty-claude-cli/src/main.rs::format_tool_call_start
    """
    try:
        params = json.loads(tool_input) if tool_input else {}
    except json.JSONDecodeError:
        params = {}

    # Tool-specific formatting
    detail = ""
    match tool_name:
        case "Bash":
            cmd = params.get("command", "")
            desc = params.get("description", "")
            detail = f"  $ {cmd}" if cmd else ""
            if desc:
                detail = f"  {desc}\n{detail}"
        case "Read":
            path = params.get("file_path", "")
            offset = params.get("offset", "")
            limit = params.get("limit", "")
            detail = f"  📄 {path}"
            if offset or limit:
                detail += f" (lines {offset or 1}-{(offset or 0) + (limit or '?')})"
        case "Write":
            path = params.get("file_path", "")
            content = params.get("content", "")
            lines = content.count("\n") + 1 if content else 0
            detail = f"  ✏️  {path} ({lines} lines)"
        case "Edit":
            path = params.get("file_path", "")
            old = params.get("old_string", "")[:60]
            new = params.get("new_string", "")[:60]
            detail = f"  📝 {path}\n  - {old!r}\n  + {new!r}"
        case "Glob":
            pattern = params.get("pattern", "")
            path = params.get("path", ".")
            detail = f"  🔍 {pattern} in {path}"
        case "Grep":
            pattern = params.get("pattern", "")
            path = params.get("path", ".")
            detail = f"  🔎 /{pattern}/ in {path}"
        case "Agent":
            desc = params.get("description", "")
            detail = f"  🤖 {desc}" if desc else ""
        case _:
            # Generic tool display
            if params:
                summary = ", ".join(f"{k}={v!r}" for k, v in list(params.items())[:3])
                if len(summary) > 100:
                    summary = summary[:100] + "..."
                detail = f"  {summary}"

    header = f"╭─ {tool_name} "
    border_len = max(60 - len(header), 4)
    header += "─" * border_len + "╮"

    lines = [header]
    if detail:
        for line in detail.split("\n"):
            lines.append(f"│ {line}")

    return "\n".join(lines)


def format_tool_result(
    tool_name: str, output: str, is_error: bool = False
) -> str:
    """Format tool execution result.

    Maps to: rust/crates/rusty-claude-cli/src/main.rs::format_tool_result
    """
    icon = "✗" if is_error else "✓"
    status = "error" if is_error else "success"

    # Truncate output
    display = output
    truncated = False
    output_lines = display.split("\n")

    if len(output_lines) > TOOL_OUTPUT_DISPLAY_MAX_LINES:
        output_lines = output_lines[:TOOL_OUTPUT_DISPLAY_MAX_LINES]
        truncated = True
    display = "\n".join(output_lines)

    if len(display) > TOOL_OUTPUT_DISPLAY_MAX_CHARS:
        display = display[:TOOL_OUTPUT_DISPLAY_MAX_CHARS]
        truncated = True

    # Tool-specific result formatting
    match tool_name:
        case "Read":
            line_count = display.count("\n") + 1
            if line_count > READ_DISPLAY_MAX_LINES:
                display_lines = display.split("\n")[:READ_DISPLAY_MAX_LINES]
                display = "\n".join(display_lines)
                truncated = True
        case "Glob":
            # Show file count
            pass
        case "Grep":
            # Show match count
            pass

    result = f"│ {icon} {tool_name} ({status})"
    if display.strip():
        # Indent output
        indented = "\n".join(f"│ {line}" for line in display.split("\n"))
        result += f"\n{indented}"

    if truncated:
        result += "\n│ ... (output truncated)"

    result += f"\n╰{'─' * 58}╯"
    return result


# ---------------------------------------------------------------------------
# Terminal renderer
# ---------------------------------------------------------------------------

class TerminalRenderer:
    """Renders conversation output to the terminal using Rich.

    Maps to: rust/crates/rusty-claude-cli/src/render.rs::TerminalRenderer
    """

    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console(theme=CLAW_THEME)

    def render_markdown(self, text: str) -> None:
        """Render markdown text to the terminal."""
        md = Markdown(text, code_theme="monokai")
        self.console.print(md)

    def render_code(self, code: str, language: str = "python") -> None:
        """Render syntax-highlighted code."""
        syntax = Syntax(code, language, theme="monokai", line_numbers=True)
        self.console.print(syntax)

    def render_text(self, text: str, style: str = "") -> None:
        """Render plain text with optional style."""
        self.console.print(text, style=style, highlight=False)

    def render_streaming_text(self, text: str) -> None:
        """Render streaming text (no newline)."""
        self.console.print(text, end="", highlight=False)

    def render_tool_call(self, tool_name: str, tool_input: str) -> None:
        """Render a tool invocation with box-drawing border."""
        formatted = format_tool_call_start(tool_name, tool_input)
        self.console.print(f"[axion.tool_border]{formatted}[/axion.tool_border]")

    def render_tool_result(self, tool_name: str, output: str, is_error: bool = False) -> None:
        """Render tool execution result."""
        formatted = format_tool_result(tool_name, output, is_error)
        style = "axion.tool_error" if is_error else "axion.tool_border"
        self.console.print(f"[{style}]{formatted}[/{style}]")

    def render_tool_use_simple(self, tool_name: str, tool_input: str) -> None:
        """Render a simple tool use indicator (no box)."""
        self.console.print(f"[axion.tool_name]⚡ {tool_name}[/axion.tool_name]")
        if tool_input:
            display = tool_input[:500] + "..." if len(tool_input) > 500 else tool_input
            self.console.print(f"  [axion.tool_input]{display}[/axion.tool_input]")

    def render_tool_result_simple(self, output: str, is_error: bool = False) -> None:
        """Render a simple tool result (no box)."""
        if is_error:
            self.console.print(f"[axion.tool_error]✗ {output}[/axion.tool_error]")
        else:
            display = output[:1000] + "\n... (truncated)" if len(output) > 1000 else output
            self.console.print(f"[axion.tool_output]{display}[/axion.tool_output]")

    def render_thinking(self, text: str) -> None:
        """Render collapsed thinking output."""
        preview = text[:100] + "..." if len(text) > 100 else text
        self.console.print(f"[axion.thinking]💭 Thinking: {preview}[/axion.thinking]")

    def render_error(self, message: str) -> None:
        """Render an error message."""
        self.console.print(f"[axion.error]Error: {message}[/axion.error]")

    def render_context_window_error(
        self,
        model: str,
        estimated_tokens: int,
        context_window: int,
        session_id: str | None = None,
    ) -> None:
        """Render a context window exceeded error with details."""
        pct = (estimated_tokens / context_window * 100) if context_window > 0 else 0
        lines = [
            "[axion.error]Context window blocked[/axion.error]",
            f"  Model: {model}",
            f"  Estimated tokens: {estimated_tokens:,}",
            f"  Context window: {context_window:,}",
            f"  Usage: {pct:.0f}%",
        ]
        if session_id:
            lines.append(f"  Session: {session_id}")
        lines.append("  Try /compact to reduce history or /clear to start fresh.")
        self.console.print("\n".join(lines))

    def render_warning(self, message: str) -> None:
        """Render a warning message."""
        self.console.print(f"[axion.warning]Warning: {message}[/axion.warning]")

    def render_info(self, message: str) -> None:
        """Render an info message."""
        self.console.print(f"[axion.info]{message}[/axion.info]")

    def render_cost(self, cost_line: str) -> None:
        """Render cost information."""
        self.console.print(f"[axion.cost]{cost_line}[/axion.cost]")

    def render_separator(self) -> None:
        """Render a horizontal separator."""
        self.console.rule(style="dim")

    def render_welcome(self, version: str, model: str) -> None:
        """Render the welcome banner."""
        self.console.print(f"\n[bold]🐍 Axion Code[/bold] v{version}")
        self.console.print(f"[dim]Model: {model}[/dim]")
        self.console.print("[dim]Type /help for commands, Ctrl+C to interrupt[/dim]\n")

    def render_status_report(
        self,
        model: str,
        permission_mode: str,
        message_count: int,
        turn_count: int,
        session_id: str,
        cwd: str,
        git_branch: str | None = None,
        estimated_tokens: int = 0,
    ) -> None:
        """Render a full status report."""
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style="bold")
        table.add_column()
        table.add_row("Model", model)
        table.add_row("Permissions", permission_mode)
        table.add_row("Messages", str(message_count))
        table.add_row("Turns", str(turn_count))
        table.add_row("Est. Tokens", f"{estimated_tokens:,}")
        table.add_row("Session", session_id)
        table.add_row("Working Dir", cwd)
        if git_branch:
            table.add_row("Git Branch", git_branch)
        self.console.print(Panel(table, title="Status", border_style="dim"))

    def render_session_list(self, sessions: list[dict[str, Any]]) -> None:
        """Render a list of sessions."""
        if not sessions:
            self.console.print("[dim]No sessions found.[/dim]")
            return
        table = Table(title="Sessions", show_lines=False)
        table.add_column("ID", style="cyan")
        table.add_column("Messages", justify="right")
        table.add_column("Modified")
        table.add_column("Branch")
        for s in sessions:
            table.add_row(
                s.get("id", "?"),
                str(s.get("message_count", 0)),
                s.get("modified", "?"),
                s.get("branch", ""),
            )
        self.console.print(table)

    def render_json_output(self, data: dict[str, Any]) -> None:
        """Render structured JSON output."""
        self.console.print_json(json.dumps(data, indent=2, default=str))

    def render_permission_prompt(
        self, tool_name: str, current_mode: str, required_mode: str, reason: str = ""
    ) -> None:
        """Render a permission approval request."""
        self.console.print()
        self.console.print("[bold yellow]Permission approval required[/bold yellow]")
        self.console.print(f"  Tool: [bold]{tool_name}[/bold]")
        self.console.print(f"  Current mode: {current_mode}")
        self.console.print(f"  Required mode: {required_mode}")
        if reason:
            self.console.print(f"  Reason: {reason}")

    def render_auto_compaction_notice(self, removed_count: int) -> None:
        """Render auto-compaction notice."""
        self.console.print(
            f"[dim]Auto-compacted: removed {removed_count} messages to stay within context window.[/dim]"
        )

    def render_export_success(self, path: str) -> None:
        """Render export success message."""
        self.console.print(f"[green]Transcript exported to: {path}[/green]")
