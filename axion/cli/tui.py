"""Terminal UI components — header bar, status bar, logo, response panels.

Provides a polished TUI experience using Rich:
- ASCII logo/brand
- Header bar with model, session, git branch
- Status bar with tokens, cost, turn count
- Response panels with borders
- Tool use panels with icons
"""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

# ---------------------------------------------------------------------------
# Axion ASCII Logo
# ---------------------------------------------------------------------------

# Neural network / node graph logo — multi-layer connected nodes
AXION_LOGO_SMALL = (
    "[#8892b0]       ⬡[/#8892b0][#00d4aa]━━━━━━━[/#00d4aa][#8892b0]⬡[/#8892b0]\n"
    "[#00d4aa]      ╱ ╲       ╱ ╲[/#00d4aa]\n"
    "[#8892b0]    ⬡[/#8892b0][#00d4aa]───╲─────╱───[/#00d4aa][#8892b0]⬡[/#8892b0]\n"
    "[#00d4aa]     ╲   ╲   ╱   ╱[/#00d4aa]\n"
    "[#00d4aa]      ╲   [bold #64ffda]⬢[/bold #64ffda]   ╱[/#00d4aa]\n"
    "[#00d4aa]      ╱   ╱ ╲   ╲[/#00d4aa]\n"
    "[#8892b0]    ⬡[/#8892b0][#00d4aa]───╱─────╲───[/#00d4aa][#8892b0]⬡[/#8892b0]\n"
    "[#00d4aa]      ╲ ╱       ╲ ╱[/#00d4aa]\n"
    "[#8892b0]       ⬡[/#8892b0][#00d4aa]━━━━━━━[/#00d4aa][#8892b0]⬡[/#8892b0]\n"
    "\n"
    "[bold #64ffda]      A X I O N[/bold #64ffda]"
)

AXION_LOGO_MINI = "[bold #00d4aa]◆ AXION[/bold #00d4aa]"


# ---------------------------------------------------------------------------
# Header bar
# ---------------------------------------------------------------------------

def render_header(
    console: Console,
    version: str,
    model: str,
    session_id: str,
    permission_mode: str = "allow",
    git_branch: str | None = None,
    plan_mode: bool = False,
) -> None:
    """Render the top header bar with model, session, and git info."""
    # Left: logo + version
    left = f"[bold cyan]◆ AXION[/bold cyan] [dim]v{version}[/dim]"

    # Center: model
    model_display = f"[bold white]{model}[/bold white]"
    if plan_mode:
        model_display += " [bold #00d4aa]⚡PLAN[/bold #00d4aa]"

    # Right: session + branch
    right_parts = [f"[dim]{session_id[:8]}[/dim]"]
    if git_branch:
        right_parts.append(f"[dim cyan]{git_branch}[/dim cyan]")
    right = " │ ".join(right_parts)

    # Build the header table (single row, 3 columns)
    header = Table(show_header=False, show_edge=False, box=None, padding=0, expand=True)
    header.add_column(ratio=1)
    header.add_column(ratio=1, justify="center")
    header.add_column(ratio=1, justify="right")
    header.add_row(left, model_display, right)

    console.print(Panel(header, style="dim", border_style="#00d4aa", padding=(0, 1)))


# ---------------------------------------------------------------------------
# Status bar (bottom)
# ---------------------------------------------------------------------------

def render_status_bar(
    console: Console,
    tokens: int = 0,
    cost: float = 0.0,
    turn: int = 0,
    permission_mode: str = "allow",
    plan_mode: bool = False,
) -> None:
    """Render the bottom status bar with tokens, cost, and turn info."""
    parts: list[str] = []

    if tokens > 0:
        parts.append(f"[dim]Tokens: {tokens:,}[/dim]")
    if cost > 0:
        parts.append(f"[dim]Cost: ${cost:.4f}[/dim]")
    if turn > 0:
        parts.append(f"[dim]Turn {turn}[/dim]")

    parts.append(f"[dim]{permission_mode}[/dim]")

    if plan_mode:
        parts.append("[bold #00d4aa]PLAN MODE[/bold #00d4aa]")

    bar_text = " │ ".join(parts) if parts else "[dim]Ready[/dim]"
    console.print(f"[dim]{'─' * 60}[/dim]")
    console.print(f"  {bar_text}")


# ---------------------------------------------------------------------------
# Welcome screen
# ---------------------------------------------------------------------------

def render_welcome_screen(
    console: Console,
    version: str,
    model: str,
    session_id: str,
    permission_mode: str = "allow",
    git_branch: str | None = None,
    resumed: bool = False,
    message_count: int = 0,
    cwd: str = "",
    auth_mode: str = "",
) -> None:
    """Render the Claude Code-style welcome screen with two columns."""
    import os
    import random

    console.print()

    # Network graph matching the logo
    mascot = (
        "[#8892b0]     ⬡[/#8892b0][#00d4aa]━━━[/#00d4aa][#8892b0]⬡[/#8892b0]\n"
        "[#00d4aa]    ╱ ╲ ╱ ╲[/#00d4aa]\n"
        "[#8892b0]   ⬡[/#8892b0][#00d4aa]─[bold #64ffda]⬢[/bold #64ffda]─[/#00d4aa][#8892b0]⬡[/#8892b0]\n"
        "[#00d4aa]    ╲ ╱ ╲ ╱[/#00d4aa]\n"
        "[#8892b0]     ⬡[/#8892b0][#00d4aa]━━━[/#00d4aa][#8892b0]⬡[/#8892b0]"
    )

    # Left column: version + mascot
    left_lines = [
        f"[dim]- - -[/dim] [bold]Axion Code[/bold] v{version} [dim]- - -[/dim]",
        "",
    ]
    if resumed:
        left_lines.append("    Welcome back!")
    else:
        left_lines.append("    Welcome!")
    left_lines.append("")
    left_lines.append(mascot)
    left_lines.append("")
    # Render model with auth mode badge.
    if auth_mode == "subscription":
        sub_label = "ChatGPT" if "codex" in model.lower() else "Pro/Max"
        model_line = f"    [bold]{model}[/bold] [bold #64ffda]· {sub_label}[/bold #64ffda]"
    elif auth_mode == "local":
        model_line = f"    [bold]{model}[/bold] [dim cyan]· local[/dim cyan]"
    elif auth_mode == "api":
        model_line = f"    [bold]{model}[/bold] [yellow]· API[/yellow]"
    else:
        model_line = f"    [bold]{model}[/bold]"
    left_lines.append(model_line)
    left_lines.append(f"    [dim]{cwd or os.getcwd()}[/dim]")

    # Right column: tips + recent activity
    right_lines = [
        "[bold #00d4aa]Quick start[/bold #00d4aa]",
    ]

    tips = [
        '"Fix the bug in auth.py"',
        '"Add tests for the API"',
        '"Explain this codebase"',
        '"Refactor this function"',
        '"Search for all TODO comments"',
        '"Read package.json and summarize"',
    ]
    selected_tips = random.sample(tips, min(3, len(tips)))
    for tip in selected_tips:
        right_lines.append(f"  [dim]Try:[/dim] {tip}")

    right_lines.append("")
    right_lines.append("[bold #00d4aa]Commands[/bold #00d4aa]")
    right_lines.append("  [bold]/plan[/bold] [dim]Design before coding[/dim]")
    right_lines.append("  [bold]/model[/bold] [dim]Switch AI model[/dim]")
    right_lines.append("  [bold]/cost[/bold] [dim]See token usage[/dim]")
    right_lines.append("  [bold]/export[/bold] [dim]Save transcript[/dim]")
    right_lines.append("  [dim]... /help for more[/dim]")

    if resumed:
        right_lines.append("")
        right_lines.append("[bold #00d4aa]Session[/bold #00d4aa]")
        right_lines.append(f"  [dim]Resumed {message_count} messages[/dim]")
        right_lines.append(f"  [dim]ID: {session_id[:12]}[/dim]")

    # Build two-column layout
    left_text = "\n".join(left_lines)
    right_text = "\n".join(right_lines)

    # Use a table for side-by-side layout
    layout = Table(show_header=False, show_edge=False, box=None, padding=(0, 3), expand=True)
    layout.add_column(ratio=1, justify="center")
    layout.add_column(ratio=1)
    layout.add_row(left_text, right_text)

    console.print(Panel(
        layout,
        border_style="#0a192f",
        padding=(1, 2),
    ))
    console.print()


# ---------------------------------------------------------------------------
# Response formatting
# ---------------------------------------------------------------------------

def render_assistant_response(console: Console, text: str) -> None:
    """Render an assistant response in a panel."""
    if not text.strip():
        return
    from rich.markdown import Markdown
    console.print()
    console.print(Markdown(text))
    console.print()


def render_tool_call_inline(
    console: Console,
    tool_name: str,
    params: dict[str, Any],
) -> None:
    """Render a tool invocation as a compact inline bullet (Claude Code style).

    Format: `● ToolName(args)` — one line, no panel, no border.
    For Edit/Write, also shows an inline mini-diff (additions/removals)
    so you can see what's changing without expanding a panel.
    """
    args_str = _format_tool_args(tool_name, params)
    if args_str:
        console.print(f"[bold #00d4aa]●[/bold #00d4aa] [bold]{tool_name}[/bold]({args_str})")
    else:
        console.print(f"[bold #00d4aa]●[/bold #00d4aa] [bold]{tool_name}[/bold]")

    # Show inline diff for Edit/Write so the user can see what changed
    if tool_name == "Edit":
        _render_edit_diff(console, params)
    elif tool_name == "Write":
        _render_write_preview(console, params)


# Maximum number of diff lines to show before truncating
_MAX_DIFF_LINES = 14


def _find_line_number_in_file(file_path: str, search_str: str) -> int:
    """Find the 1-based line number where search_str starts in file_path.

    Returns 1 if the file can't be read or the string isn't found.
    """
    if not file_path or not search_str:
        return 1
    try:
        from pathlib import Path as _P
        p = _P(file_path)
        if not p.exists():
            return 1
        content = p.read_text(encoding="utf-8", errors="replace")
        pos = content.find(search_str)
        if pos < 0:
            # If old_string isn't there anymore (already replaced), search for new_string
            return 1
        return content[:pos].count("\n") + 1
    except (OSError, UnicodeDecodeError):
        return 1


def _render_edit_diff(console: Console, params: dict[str, Any]) -> None:
    """Render an inline diff for Edit calls with line numbers and bg colors.

    Style matches Claude Code:
        4  -Software engineering has undergone...        (red bg)
        4  +Software engineering has undergone...        (green bg)
    """
    old_str = params.get("old_string", "") or ""
    new_str = params.get("new_string", "") or ""
    file_path = params.get("file_path", "") or ""
    if not old_str and not new_str:
        return

    old_lines = old_str.splitlines() if old_str else []
    new_lines = new_str.splitlines() if new_str else []

    # Anchor line: where old_str (or new_str if already applied) starts
    start_line = _find_line_number_in_file(file_path, old_str) if old_str else _find_line_number_in_file(file_path, new_str)

    shown_old = old_lines[:_MAX_DIFF_LINES]
    shown_new = new_lines[:_MAX_DIFF_LINES]

    # Print removed lines with red background
    for i, line in enumerate(shown_old):
        ln = start_line + i
        text = _truncate_line(line)
        console.print(f"  [dim]{ln:>4}[/dim]  [white on red] -{text} [/white on red]")
    if len(old_lines) > _MAX_DIFF_LINES:
        hidden = len(old_lines) - _MAX_DIFF_LINES
        console.print(f"  [dim]      ... {hidden} more removed line(s)[/dim]")

    # Print added lines with green background — same anchor line so alignment matches
    for i, line in enumerate(shown_new):
        ln = start_line + i
        text = _truncate_line(line)
        console.print(f"  [dim]{ln:>4}[/dim]  [white on green] +{text} [/white on green]")
    if len(new_lines) > _MAX_DIFF_LINES:
        hidden = len(new_lines) - _MAX_DIFF_LINES
        console.print(f"  [dim]      ... {hidden} more added line(s)[/dim]")


def _render_write_preview(console: Console, params: dict[str, Any]) -> None:
    """Render the new file's content with line numbers (Claude Code style).

        1  The Evolution of Software Engineering: A...
        2
        3  Software engineering has undergone...
       ... +67 lines (ctrl+o to expand)
    """
    content = params.get("content", "") or ""
    if not content:
        return
    lines = content.splitlines()
    shown = lines[:_MAX_DIFF_LINES]
    for i, line in enumerate(shown, start=1):
        text = _truncate_line(line)
        console.print(f"  [dim]{i:>4}[/dim]  [green]{text}[/green]")
    if len(lines) > _MAX_DIFF_LINES:
        hidden = len(lines) - _MAX_DIFF_LINES
        console.print(f"  [dim]      ... +{hidden} lines (ctrl+o to expand)[/dim]")


def _truncate_line(line: str, max_chars: int = 200) -> str:
    """Truncate a line for inline display, escaping Rich markup."""
    # Escape Rich tag characters to avoid mis-rendering
    escaped = line.replace("[", r"\[")
    if len(escaped) > max_chars:
        return escaped[:max_chars] + "..."
    return escaped


def render_tool_result_inline(
    console: Console,
    tool_name: str,
    output: str,
    is_error: bool = False,
) -> None:
    """Render a tool result as an indented continuation line.

    Format: `  └ summary text` — compact, one or two lines max.
    Errors are shown in red.
    """
    if is_error:
        first_line = output.strip().splitlines()[0] if output.strip() else "error"
        # Don't duplicate the "Error:" prefix if the message already has it
        if first_line.lower().startswith(("error:", "error ", "exception:", "failed:")):
            console.print(f"  [dim]└[/dim] [red]{first_line[:140]}[/red]")
        else:
            console.print(f"  [dim]└[/dim] [red]Error: {first_line[:140]}[/red]")
        return

    summary = _summarize_tool_output(tool_name, output)
    console.print(f"  [dim]└[/dim] [dim]{summary}[/dim]")


def _format_tool_args(tool_name: str, params: dict[str, Any]) -> str:
    """Build a one-line argument display for a tool call."""
    if tool_name == "Bash":
        cmd = params.get("command", "")
        return cmd[:120] + ("..." if len(cmd) > 120 else "")
    if tool_name == "Read":
        return params.get("file_path", "")
    if tool_name in ("Write", "Edit"):
        return params.get("file_path", "")
    if tool_name == "Glob":
        return params.get("pattern", "")
    if tool_name == "Grep":
        pattern = params.get("pattern", "")
        path = params.get("path", "")
        return f'"{pattern}"' + (f" in {path}" if path else "")
    if tool_name == "WebSearch":
        return f'"{params.get("query", "")[:100]}"'
    if tool_name == "WebFetch":
        return params.get("url", "")
    if tool_name == "Agent":
        desc = params.get("description", "")
        return desc[:100]
    if tool_name == "TodoWrite":
        todos = params.get("todos", [])
        return f"{len(todos)} task(s)"
    if tool_name == "NotebookEdit":
        return params.get("notebook_path", "")
    if tool_name == "Skill":
        return params.get("skill", "")
    # Generic: first param value
    for v in params.values():
        s = str(v)
        return s[:100] + ("..." if len(s) > 100 else "")
    return ""


def _summarize_tool_output(tool_name: str, output: str) -> str:
    """One-line summary of tool output for the inline result display."""
    if not output.strip():
        return "done"
    line_count = len(output.splitlines())

    if tool_name == "Bash":
        # First non-empty line + count if multi-line
        lines = [l for l in output.splitlines() if l.strip()]
        first = lines[0][:120] if lines else "(no output)"
        return f"{first}" + (f"  [dim]({line_count} lines)[/dim]" if line_count > 1 else "")
    if tool_name == "Read":
        return f"Read {line_count} lines"
    if tool_name in ("Write", "Edit"):
        first = output.splitlines()[0][:120] if output.strip() else "done"
        return first
    if tool_name == "Glob":
        # Output: "Found N file(s) in Xms:" + paths
        first_line = output.splitlines()[0] if output.strip() else "0 results"
        return first_line[:120]
    if tool_name == "Grep":
        first_line = output.splitlines()[0] if output.strip() else "0 matches"
        return first_line[:120]
    if tool_name == "WebSearch":
        return f"Found {max(line_count - 2, 0)} result(s)"
    if tool_name == "WebFetch":
        return f"Fetched {len(output):,} chars"
    if tool_name == "Agent":
        first = output.splitlines()[0] if output.strip() else "done"
        return first[:120]
    if tool_name == "TodoWrite":
        return "Updated"
    # Generic
    first = output.splitlines()[0][:120] if output.strip() else "done"
    return first


def render_tool_panel(
    console: Console,
    tool_name: str,
    params: dict[str, Any],
    is_start: bool = True,
) -> None:
    """Render a tool invocation with diff-style display for Edit/Write."""
    if not is_start:
        return

    icon = _tool_icon(tool_name)
    title = f"{icon} {tool_name}"
    lines: list[str] = []

    if tool_name == "Edit" and "file_path" in params:
        # Show edit as a diff — background colored, real line numbers from file
        file_path = params.get("file_path", "")
        old_str = params.get("old_string", "")
        new_str = params.get("new_string", "")
        old_lines_list = old_str.splitlines() if old_str else []
        new_lines_list = new_str.splitlines() if new_str else []

        lines.append(f"  [dim]file:[/dim] {file_path}")
        count_info = f"{len(new_lines_list)} addition{'s' if len(new_lines_list) != 1 else ''} and {len(old_lines_list)} removal{'s' if len(old_lines_list) != 1 else ''}"
        lines.append(f"  [dim]{count_info}[/dim]")
        lines.append("")

        # Try to find real line number where old_string starts in the file
        start_line = 1
        try:
            from pathlib import Path as _Path
            fp = _Path(file_path)
            if fp.exists() and old_str:
                file_content = fp.read_text(encoding="utf-8", errors="replace")
                pos = file_content.find(old_str)
                if pos >= 0:
                    start_line = file_content[:pos].count("\n") + 1
                # If old_str not found (already replaced), try new_str
                elif new_str:
                    pos = file_content.find(new_str)
                    if pos >= 0:
                        start_line = file_content[:pos].count("\n") + 1
        except Exception:
            pass

        line_num = start_line
        # Show removed lines with RED background
        for old_line in old_lines_list[:10]:
            lines.append(f"  [dim]{line_num:>4}[/dim] [on red] {old_line} [/on red]")
            line_num += 1
        # Show added lines with GREEN background
        line_num = start_line  # Reset — new lines replace at same position
        for new_line in new_lines_list[:10]:
            lines.append(f"  [dim]{line_num:>4}[/dim] [on green] {new_line} [/on green]")
            line_num += 1

        total = len(old_lines_list) + len(new_lines_list)
        if total > 10:
            lines.append(f"  [dim]     ... ({total} lines total)[/dim]")

    elif tool_name == "Write" and "file_path" in params:
        # Show write with GREEN background lines + line numbers
        file_path = params.get("file_path", "")
        content = params.get("content", "")
        content_lines = content.splitlines() if content else []
        line_count = len(content_lines)

        lines.append(f"  [dim]file:[/dim] {file_path}")
        lines.append(f"  [dim]{line_count} line{'s' if line_count != 1 else ''}[/dim]")
        lines.append("")

        for i, cl in enumerate(content_lines[:8], 1):
            lines.append(f"  [dim]{i:>4}[/dim] [on green] {cl} [/on green]")
        if line_count > 8:
            lines.append(f"  [dim]     ... ({line_count} lines total)[/dim]")

    elif tool_name == "Bash":
        cmd = params.get("command", "")
        desc = params.get("description", "")
        if desc:
            lines.append(f"  [dim]{desc}[/dim]")
        lines.append(f"  [bold]$ {cmd}[/bold]")

    elif tool_name == "Read":
        file_path = params.get("file_path", "")
        lines.append(f"  [dim]file:[/dim] {file_path}")

    else:
        # Generic display
        for key, value in list(params.items())[:5]:
            val_str = str(value)
            if len(val_str) > 150:
                val_str = val_str[:150] + "..."
            lines.append(f"  [dim]{key}:[/dim] {val_str}")

    content = "\n".join(lines) if lines else "[dim]No parameters[/dim]"
    console.print(Panel(
        content,
        title=f"[bold #00d4aa]{title}[/bold #00d4aa]",
        title_align="left",
        border_style="#00d4aa",
        padding=(0, 1),
    ))


def render_tool_result_panel(
    console: Console,
    tool_name: str,
    output: str,
    is_error: bool = False,
) -> None:
    """Render a tool result with appropriate styling.

    - Edit/Write results: show with dim text (not bold)
    - Read results: show with line numbers faded
    - Bash results: stdout normal, stderr red
    - Errors: red border
    """
    icon = "✗" if is_error else "✓"
    color = "red" if is_error else "green"

    # Truncate long output
    display = output
    if len(display) > 1200:
        display = display[:1200] + "\n[dim]... (truncated)[/dim]"

    # Style based on tool type
    if tool_name in ("Edit", "Write") and not is_error:
        # Show edit/write result in dim (it's just a confirmation)
        display = f"[dim]{display}[/dim]"
    elif tool_name == "Read" and not is_error:
        # Show with dim line numbers, normal content text
        styled_lines = []
        for line in display.splitlines()[:40]:
            if "\t" in line:
                num, rest = line.split("\t", 1)
                styled_lines.append(f"  [dim]{num:>4}[/dim]  {rest}")
            else:
                styled_lines.append(f"        {line}")
        display = "\n".join(styled_lines)
        if len(output.splitlines()) > 40:
            display += f"\n  [dim]     ... ({len(output.splitlines())} lines total)[/dim]"
    elif tool_name == "Bash" and not is_error:
        # Highlight stderr in red within bash output
        styled_lines = []
        in_stderr = False
        for line in display.splitlines():
            if line.startswith("STDERR:"):
                in_stderr = True
                styled_lines.append(f"[red]{line}[/red]")
            elif in_stderr and line.startswith("Exit code:"):
                styled_lines.append(f"[yellow]{line}[/yellow]")
                in_stderr = False
            elif in_stderr:
                styled_lines.append(f"[red]{line}[/red]")
            else:
                styled_lines.append(line)
        display = "\n".join(styled_lines)

    console.print(Panel(
        display,
        title=f"[bold {color}]{icon} {tool_name}[/bold {color}]",
        title_align="left",
        border_style=color,
        padding=(0, 1),
    ))


def _tool_icon(tool_name: str) -> str:
    """Get an icon for a tool name."""
    icons = {
        "Bash": "⚡",
        "Read": "📄",
        "Write": "✏️",
        "Edit": "📝",
        "Glob": "🔍",
        "Grep": "🔎",
        "WebSearch": "🌐",
        "WebFetch": "🌍",
        "Agent": "🤖",
        "TodoWrite": "📋",
        "NotebookEdit": "📓",
        "Skill": "⚙️",
        "ToolSearch": "🔧",
    }
    return icons.get(tool_name, "⚡")


# ---------------------------------------------------------------------------
# Cost display
# ---------------------------------------------------------------------------

def render_turn_cost(
    console: Console,
    tokens: int,
    cost: float,
    turn: int,
    auth_mode: str = "",
) -> None:
    """Render the cost line after a turn."""
    if tokens <= 0:
        return
    if auth_mode == "subscription":
        # No per-token billing — show subscription badge instead of $cost
        cost_part = "[dim #64ffda]Pro/Max[/dim #64ffda]"
    else:
        cost_part = f"[dim cyan]${cost:.4f}[/dim cyan]"
    console.print(
        f"  [dim]---[/dim] [dim cyan]Tokens: {tokens:,}[/dim cyan]"
        f" [dim]|[/dim] {cost_part}"
        f" [dim]|[/dim] [dim]Turn {turn}[/dim]"
    )


# ---------------------------------------------------------------------------
# Permission prompt styling
# ---------------------------------------------------------------------------

def render_session_history(
    console: Console,
    messages: list[Any],
) -> None:
    """Replay the full conversation exactly as it looked when it was live.

    Uses the same render_tool_panel / render_tool_result_panel / Markdown
    rendering that the live REPL uses, so resuming a session looks identical
    to scrolling up in the original conversation.
    """
    from rich.markdown import Markdown
    import json as _json

    if not messages:
        return

    for msg in messages:
        role = msg.role.value if hasattr(msg.role, "value") else str(msg.role)

        # ---- User message ----
        if role == "user":
            # Check if this is a tool-result message (user role with ToolResultBlocks)
            has_tool_results = any(
                hasattr(b, "tool_name") and hasattr(b, "output")
                for b in msg.blocks
            )
            if has_tool_results:
                # Compact inline tool result lines
                for block in msg.blocks:
                    if hasattr(block, "tool_name") and hasattr(block, "output"):
                        render_tool_result_inline(
                            console,
                            block.tool_name,
                            block.output,
                            getattr(block, "is_error", False),
                        )
                continue

            # Regular user text message — render like the prompt line
            text_parts: list[str] = []
            for block in msg.blocks:
                if hasattr(block, "text") and block.text:
                    text_parts.append(block.text)
            if not text_parts:
                continue
            user_text = "\n".join(text_parts)
            # Skip internal turn triggers
            if user_text.startswith("__RUN_TURN__:"):
                continue
            console.print()
            console.print(f"[bold #00d4aa]> [/bold #00d4aa]{user_text}")

        # ---- Assistant message → text + inline tool calls ----
        elif role == "assistant":
            for block in msg.blocks:
                if hasattr(block, "text") and block.text:
                    console.print()
                    console.print(Markdown(block.text))

                elif hasattr(block, "name") and hasattr(block, "id"):
                    # ToolUseBlock — compact inline display
                    tool_name = block.name
                    raw_input = block.input if isinstance(block.input, str) else str(block.input)
                    try:
                        params = _json.loads(raw_input) if raw_input else {}
                    except (_json.JSONDecodeError, TypeError):
                        params = {"input": raw_input[:200]} if raw_input else {}
                    render_tool_call_inline(console, tool_name, params)

    console.print()
    console.print("[bold #64ffda]  Continuing session...[/bold #64ffda]")
    console.print()


def render_permission_panel(
    console: Console,
    tool_name: str,
    mode: str,
    required: str,
    reason: str = "",
    input_preview: str = "",
) -> None:
    """Render a permission prompt in a styled panel."""
    lines = [
        f"  [bold]Tool:[/bold]     {tool_name}",
        f"  [bold]Mode:[/bold]     {mode} → needs {required}",
    ]
    if reason:
        lines.append(f"  [bold]Reason:[/bold]   {reason}")
    if input_preview:
        display = input_preview[:250] + "..." if len(input_preview) > 250 else input_preview
        lines.append(f"  [bold]Input:[/bold]    [dim]{display}[/dim]")

    console.print(Panel(
        "\n".join(lines),
        title="[bold #00d4aa]⚠ Permission Required[/bold #00d4aa]",
        title_align="left",
        border_style="#00d4aa",
        padding=(0, 1),
    ))
