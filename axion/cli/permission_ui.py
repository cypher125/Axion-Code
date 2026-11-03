"""Inline arrow-key selector for permission prompts.

Renders a Claude Code-style numbered selector that the user can navigate with
Up/Down (or 1/2/3 number keys) and confirm with Enter. The selector erases
itself when the user picks, so only the chosen line stays in scrollback.

Used by the interactive permission prompter when a destructive tool call
needs user approval.
"""

from __future__ import annotations

from typing import Any

from prompt_toolkit.application import Application
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import Layout
from prompt_toolkit.layout.containers import Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.styles import Style

# Style for the inline selector. Mirrors the navy/teal axion palette.
SELECTOR_STYLE = Style.from_dict({
    "question": "#ccd6f6 bold",
    "option.selected": "#00d4aa bold",
    "option.unselected": "#8892b0",
    "option.cursor": "#00d4aa bold",
    "hint": "#4a5568",
})


async def select_option(
    question: str,
    options: list[str],
    default: int = 0,
) -> int | None:
    """Render a Claude Code-style numbered selector inline.

    Args:
        question: The prompt shown above the option list.
        options: 2-9 short option labels.
        default: Index of the option that starts highlighted (0-based).

    Returns:
        The index (0-based) of the chosen option, or None if the user
        pressed Esc/Ctrl+C.

    Keys:
        Up/Down or k/j   navigate
        1-9              jump-and-select an option directly
        Enter            confirm the highlighted option
        Esc / Ctrl+C     cancel (returns None)
    """
    if not options:
        raise ValueError("options must be a non-empty list")
    if not (0 <= default < len(options)):
        default = 0
    if len(options) > 9:
        raise ValueError("only 1-9 numeric shortcuts are supported")

    # Mutable state held in a single-item list for closure capture
    state = {"selected": default, "done": False}

    def get_lines() -> FormattedText:
        lines: list[tuple[str, str]] = []
        lines.append(("class:question", f"{question}\n"))
        for i, opt in enumerate(options):
            if i == state["selected"]:
                lines.append(("class:option.cursor", f"❯ {i + 1}. {opt}\n"))
            else:
                lines.append(("class:option.unselected", f"  {i + 1}. {opt}\n"))
        lines.append((
            "class:hint",
            "  ↑/↓ navigate · 1-9 jump · Enter confirm · Esc cancel",
        ))
        return FormattedText(lines)

    bindings = KeyBindings()

    @bindings.add(Keys.Up)
    @bindings.add("k")
    def _up(event: Any) -> None:
        state["selected"] = (state["selected"] - 1) % len(options)
        event.app.invalidate()

    @bindings.add(Keys.Down)
    @bindings.add("j")
    def _down(event: Any) -> None:
        state["selected"] = (state["selected"] + 1) % len(options)
        event.app.invalidate()

    @bindings.add(Keys.Enter)
    def _enter(event: Any) -> None:
        event.app.exit(result=state["selected"])

    @bindings.add(Keys.Escape, eager=True)
    @bindings.add(Keys.ControlC)
    def _cancel(event: Any) -> None:
        event.app.exit(result=None)

    # Numeric shortcuts 1-9 → jump to that option and confirm immediately
    for i in range(len(options)):
        @bindings.add(str(i + 1))
        def _num(event: Any, idx: int = i) -> None:
            state["selected"] = idx
            event.app.exit(result=idx)

    # +2 rows: one for the question line, one for the hint line
    height = Dimension.exact(len(options) + 2)

    layout = Layout(
        Window(
            content=FormattedTextControl(get_lines, focusable=True),
            height=height,
            always_hide_cursor=True,
        )
    )

    app: Application[int | None] = Application(
        layout=layout,
        key_bindings=bindings,
        style=SELECTOR_STYLE,
        full_screen=False,
        mouse_support=False,
        # Erase the selector when done so only the chosen line stays in
        # scrollback (echoed by the caller). Keeps the transcript clean.
        erase_when_done=True,
    )

    try:
        return await app.run_async()
    except (EOFError, KeyboardInterrupt):
        return None
