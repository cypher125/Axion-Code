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

# Network node graph logo — represents AI connections
AXION_LOGO_SMALL = (
    "[#00d4aa]        ●───────●[/#00d4aa]\n"
    "[#00d4aa]       ╱ ╲     ╱ [/#00d4aa]\n"
    "[#00d4aa]      ●   ╲   ╱  [/#00d4aa]\n"
    "[#00d4aa]       ╲   [bold #64ffda]◆[/bold #64ffda]──●   [/#00d4aa]\n"
    "[#00d4aa]        ╲ ╱ ╲     [/#00d4aa]\n"
    "[#00d4aa]         ●   ●    [/#00d4aa]\n"
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
) -> None:
    """Render the Claude Code-style welcome screen with two columns."""
    import os
    import random

    console.print()

    # Network graph mascot matching the logo
    mascot = (
        "[#00d4aa]      ●───●[/#00d4aa]\n"
        "[#00d4aa]     ╱ ╲ ╱ [/#00d4aa]\n"
        "[#00d4aa]    ●  [bold #64ffda]◆[/bold #64ffda]──●[/#00d4aa]\n"
        "[#00d4aa]     ╲ ╱ ╲ [/#00d4aa]\n"
        "[#00d4aa]      ●───●[/#00d4aa]"
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
    left_lines.append(f"    [bold]{model}[/bold]")
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
) -> None:
    """Render the cost line after a turn."""
    if tokens <= 0:
        return
    console.print(
        f"  [dim]───[/dim] [dim cyan]Tokens: {tokens:,}[/dim cyan]"
        f" [dim]│[/dim] [dim cyan]${cost:.4f}[/dim cyan]"
        f" [dim]│[/dim] [dim]Turn {turn}[/dim]"
    )


# ---------------------------------------------------------------------------
# Permission prompt styling
# ---------------------------------------------------------------------------

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
