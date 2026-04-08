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

AXION_LOGO_SMALL = """[bold cyan]
  ╔═╗╦ ╦╦╔═╗╔╗╔
  ╠═╣╔╩╦╝║║ ║║║║
  ╩ ╩╩ ╚═╩╚═╝╝╚╝[/bold cyan]"""

AXION_LOGO_MINI = "[bold cyan]◆ AXION[/bold cyan]"


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
        model_display += " [bold yellow]⚡PLAN[/bold yellow]"

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

    console.print(Panel(header, style="dim", border_style="cyan", padding=(0, 1)))


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
        parts.append("[bold yellow]PLAN MODE[/bold yellow]")

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
) -> None:
    """Render the full welcome screen with logo and info."""
    console.print()

    # Logo
    console.print(AXION_LOGO_SMALL)
    console.print()

    # Info panel
    info_lines: list[str] = [
        f"  [bold]Version[/bold]     v{version}",
        f"  [bold]Model[/bold]       {model}",
        f"  [bold]Session[/bold]     {session_id[:12]}...",
        f"  [bold]Permissions[/bold] {permission_mode}",
    ]
    if git_branch:
        info_lines.append(f"  [bold]Branch[/bold]      {git_branch}")
    if resumed:
        info_lines.append(f"  [bold]Resumed[/bold]     {message_count} messages")

    console.print(Panel(
        "\n".join(info_lines),
        border_style="cyan",
        padding=(0, 1),
    ))

    console.print("  [dim]Type[/dim] [bold]/help[/bold] [dim]for commands,[/dim] [bold]Ctrl+C[/bold] [dim]to interrupt[/dim]")
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
    """Render a tool invocation or result in a styled panel."""
    if is_start:
        # Tool invocation header
        icon = _tool_icon(tool_name)
        title = f"{icon} {tool_name}"

        # Format key parameters
        lines: list[str] = []
        for key, value in list(params.items())[:5]:
            val_str = str(value)
            if len(val_str) > 150:
                val_str = val_str[:150] + "..."
            lines.append(f"  [dim]{key}:[/dim] {val_str}")

        content = "\n".join(lines) if lines else "[dim]No parameters[/dim]"
        console.print(Panel(
            content,
            title=f"[bold yellow]{title}[/bold yellow]",
            title_align="left",
            border_style="yellow",
            padding=(0, 1),
        ))


def render_tool_result_panel(
    console: Console,
    tool_name: str,
    output: str,
    is_error: bool = False,
) -> None:
    """Render a tool result in a styled panel."""
    icon = "✗" if is_error else "✓"
    color = "red" if is_error else "green"

    # Truncate long output
    display = output
    if len(display) > 800:
        display = display[:800] + "\n... (truncated)"

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
        title="[bold yellow]⚠ Permission Required[/bold yellow]",
        title_align="left",
        border_style="yellow",
        padding=(0, 1),
    ))
