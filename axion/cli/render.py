"""Rich-based terminal rendering: markdown, syntax highlighting, spinners.

Maps to: rust/crates/rusty-claude-cli/src/render.rs
"""

from __future__ import annotations

import enum
import json
import os
import sys
from typing import Any, Callable

from rich.console import Console
from rich.markdown import Heading, Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Compact Markdown (no full-width heading rules)
# ---------------------------------------------------------------------------
#
# Rich's default Heading draws a horizontal Rule across the full terminal
# width above H1 and below H2. In wide terminals (cmd.exe, tmux, etc.) those
# rules become extremely long horizontal lines that visually overpower the
# heading text itself. This subclass omits the rules and just bolds/colors
# the heading inline.

class CompactHeading(Heading):
    """Heading without the full-width Rule that ships with Rich's default."""

    def __rich_console__(self, console, options):  # type: ignore[override]
        text = Text(self.text.plain, style="")
        if self.tag == "h1":
            text.stylize("bold #00d4aa")
            yield text
        elif self.tag == "h2":
            text.stylize("bold #64ffda")
            yield text
        elif self.tag == "h3":
            text.stylize("bold")
            yield text
        else:
            text.stylize("italic")
            yield text


class CompactMarkdown(Markdown):
    """Drop-in Markdown replacement that uses CompactHeading for H1/H2/H3."""

    elements = {**Markdown.elements, "heading_open": CompactHeading}

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


# Navy/Cyan theme inspired by modern terminal UIs
CLAW_THEME = Theme({
    "axion.prompt": "#00d4aa bold",       # Bright teal/cyan for prompt
    "axion.assistant": "#e0e0e0",          # Light gray for response text
    "axion.tool_name": "#00d4aa bold",     # Teal for tool names
    "axion.tool_border": "#0a192f",        # Dark navy for borders
    "axion.tool_input": "#8892b0",         # Muted blue-gray for inputs
    "axion.tool_output": "#64ffda",        # Mint green for outputs
    "axion.tool_success": "#64ffda bold",  # Bright mint for success
    "axion.tool_error": "#ff6b6b bold",    # Coral red for errors
    "axion.error": "#ff6b6b bold",         # Coral red
    "axion.warning": "#ffd93d",            # Warm yellow
    "axion.info": "#8892b0",              # Muted blue-gray
    "axion.cost": "#00d4aa dim",           # Dim teal for cost
    "axion.status": "#8892b0",             # Muted blue-gray
    "axion.heading": "#ccd6f6 bold",       # Light blue-white for headings
    "axion.code": "#64ffda",              # Mint green for code
    "axion.link": "#00d4aa underline",     # Teal links
    "axion.thinking": "#8892b0 italic",    # Muted italic for thinking
    "axion.success_text": "#64ffda",       # Mint green
    "axion.dim": "#8892b0",               # Muted blue-gray for dim text
})


# ---------------------------------------------------------------------------
# Spinner (matching Rust 10-frame braille spinner)
# ---------------------------------------------------------------------------

def spinner_mode(console: Console) -> str:
    """Whether to run the spinner: 'animate' on any real terminal, else 'off'.

    The spinner animates by redrawing one line with a carriage return (``\\r``) and never emits VT
    escape codes, so it's safe on every terminal including legacy Windows cmd.exe (which leaked the
    old Rich-Status ``ESC[K``). Off when output isn't a TTY or the user set AXION_NO_SPINNER.
    """
    if os.environ.get("AXION_NO_SPINNER", "").strip().lower() in ("1", "true", "yes"):
        return "off"
    try:
        return "animate" if console.is_terminal else "off"
    except Exception:
        return "off"


_VT_ENABLED: bool | None = None


def enable_windows_vt() -> bool:
    """Turn on ANSI/VT processing for the Windows console so in-place rendering (Rich Live tables,
    the typing region) works on cmd.exe / conhost instead of leaking ``[K``. No-op returning True
    off Windows. Idempotent — call once at startup, before creating Live displays.
    """
    global _VT_ENABLED
    if _VT_ENABLED is not None:
        return _VT_ENABLED
    if sys.platform != "win32":
        _VT_ENABLED = True
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        enable_vt = 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        ok = False
        for handle_id in (-11, -12):  # STD_OUTPUT_HANDLE, STD_ERROR_HANDLE
            handle = kernel32.GetStdHandle(handle_id)
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                if kernel32.SetConsoleMode(handle, mode.value | enable_vt):
                    ok = True
        _VT_ENABLED = ok
    except Exception:
        _VT_ENABLED = False
    return _VT_ENABLED


def rich_live_ok(console: Console) -> bool:
    """Whether Rich ``Live`` (VT cursor control) renders cleanly here.

    The per-token typing region and the agent dashboard rely on VT escapes. On Windows that needs
    VT processing switched on (see enable_windows_vt); if we couldn't enable it, fall back to the
    non-VT line modes. AXION_STREAM=lines / a legacy console also force the fallback.
    """
    if os.environ.get("AXION_STREAM", "").strip().lower() == "lines":
        return False  # single kill-switch for all in-place VT rendering (typing + dashboard)
    try:
        if not console.is_terminal:
            return False
        if getattr(console, "legacy_windows", False):
            return False
        if sys.platform == "win32":
            return bool(_VT_ENABLED) or bool(os.environ.get("WT_SESSION"))
        return True
    except Exception:
        return False


class Spinner:
    """Animated progress indicator that works on every terminal and never leaks escape codes.

    It runs a background thread that redraws a single line with a carriage return (``\\r``) — no VT
    cursor/erase codes — so cmd.exe animates cleanly instead of frozen-looking or spewing ``[K``.
    Maps to: render.rs::Spinner.
    """

    _FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console(stderr=True)
        self._running = False
        self._label = ""
        self._thread: Any | None = None
        self._stop_evt: Any | None = None

    def _stream(self) -> Any:
        # Write straight to the underlying stream so we bypass Rich's line control.
        return getattr(self._console, "file", None) or sys.stdout

    def start(self, label: str = "Thinking...") -> None:
        """Start the spinner (animated on a TTY, no-op otherwise)."""
        self._running = True
        self._label = label
        if spinner_mode(self._console) != "animate":
            return
        import threading

        self._stop_evt = threading.Event()
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self) -> None:
        import itertools
        import time

        stream = self._stream()
        for frame in itertools.cycle(self._FRAMES):
            if self._stop_evt is None or self._stop_evt.is_set():
                break
            try:
                stream.write(f"\r{frame} {self._label} ")
                stream.flush()
            except Exception:
                break
            time.sleep(0.08)

    def _clear_line(self) -> None:
        try:
            stream = self._stream()
            stream.write("\r" + " " * (len(self._label) + 4) + "\r")
            stream.flush()
        except Exception:
            pass

    def stop(self, final_label: str | None = None, success: bool = True) -> None:
        """Stop the spinner, clear its line, and optionally show a final status."""
        self._running = False
        if self._thread is not None:
            if self._stop_evt is not None:
                self._stop_evt.set()
            self._thread.join(timeout=0.3)
            self._thread = None
            self._stop_evt = None
            self._clear_line()
        if final_label:
            icon = "[green]✔[/green]" if success else "[red]✘[/red]"
            self._console.print(f"{icon} {final_label}")

    def finish(self, label: str = "Done") -> None:
        """Stop with success indicator."""
        self.stop(label, success=True)

    def fail(self, label: str = "Failed") -> None:
        """Stop with failure indicator."""
        self.stop(label, success=False)


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

    # -- Line-granular streaming (smooth output) --------------------------------------------
    # The block-boundary methods above only reveal text at a blank line or a *closed* code
    # fence, so on a slow model the cursor sits frozen through a long paragraph or code block
    # and then the whole thing dumps at once. These stream each COMPLETED line the moment its
    # newline arrives, which reads like Claude Code's live output. Prose lines are tagged "md"
    # (render as Markdown, inline formatting kept); lines inside a ``` fence are tagged "raw"
    # (print verbatim, preserving indentation) so code appears line by line as it's generated.

    def _classify_line(self, line: str) -> tuple[str, str]:
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            self._in_code_fence = not self._in_code_fence
            return ("raw", line)  # the fence delimiter itself
        if self._in_code_fence:
            return ("raw", line)
        return ("md", line)

    def push_stream(self, delta: str) -> list[tuple[str, str]]:
        """Accumulate *delta* and return [(kind, text)] for every newly completed line.

        Holds the incomplete trailing line until its newline arrives. kind is "md" or "raw".
        """
        self._pending += delta
        out: list[tuple[str, str]] = []
        while "\n" in self._pending:
            line, self._pending = self._pending.split("\n", 1)
            out.append(self._classify_line(line))
        return out

    def flush_stream(self) -> list[tuple[str, str]]:
        """Return the trailing partial line (call at a tool boundary or end of turn)."""
        if not self._pending.strip():
            self._pending = ""
            return []
        line, self._pending = self._pending, ""
        return [self._classify_line(line)]

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


class LiveStreamer:
    """Per-token streaming, like Claude Code's live output.

    Completed lines scroll up into the terminal history (rendered by ``emit_line``), while the
    in-progress *trailing* line shows in a one-line Rich ``Live`` region that updates as tokens
    arrive — so text visibly types out mid-line instead of only appearing when the line finishes.

    The Live region only ever holds the single current line, so it never fights the terminal
    height and handles arbitrarily long replies. If Rich ``Live`` can't run (not a TTY) or is
    disabled with ``AXION_STREAM=lines``, it degrades cleanly to line-granular streaming: the
    partial line just appears once its newline arrives.
    """

    def __init__(
        self,
        console: Console,
        state: MarkdownStreamState,
        emit_line: Callable[[str, str], None],
    ) -> None:
        self.console = console
        self.state = state
        self.emit_line = emit_line
        self._live: Any | None = None
        # Only run the in-place Live region where the terminal can animate cleanly (else its cursor
        # / erase-line codes leak as ``[K`` on cmd.exe). Falls back to line-granular streaming, which
        # uses plain prints and never leaks. AXION_STREAM=lines forces the fallback everywhere.
        self._enabled = (
            os.environ.get("AXION_STREAM", "live").strip().lower() != "lines"
            and rich_live_ok(console)
        )

    def _ensure_live(self) -> None:
        if self._live is not None or not self._enabled:
            return
        try:
            from rich.live import Live

            self._live = Live(
                Text(""),
                console=self.console,
                refresh_per_second=15,
                transient=True,
                vertical_overflow="visible",
            )
            self._live.start()
        except Exception:
            self._live = None
            self._enabled = False  # give up on Live for the rest of the session

    def _set_partial(self, text: str) -> None:
        if self._live is None:
            return
        try:
            self._live.update(Text(text))
        except Exception:
            pass

    def push(self, delta: str) -> None:
        completed = self.state.push_stream(delta)
        if completed and self._live is not None:
            self._set_partial("")  # clear the stale partial before printing finished lines above it
        for kind, line in completed:
            try:
                self.emit_line(kind, line)
            except Exception:
                pass
        partial = self.state._pending
        if partial:
            self._ensure_live()
            self._set_partial(partial)

    def finish(self) -> bool:
        """Stop the live region and render the trailing partial as a finished line.

        Returns True if a trailing line was emitted. Resets fence state for the next message.
        Safe to call repeatedly and from error paths.
        """
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None
        tail = self.state.flush_stream()
        for kind, line in tail:
            try:
                self.emit_line(kind, line)
            except Exception:
                pass
        self.state._in_code_fence = False
        return bool(tail)


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
        md = CompactMarkdown(text, code_theme="monokai")
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
        from axion.cli.brand import brand_name

        self.console.print(f"\n[bold]🐍 {brand_name()}[/bold] v{version}")
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
