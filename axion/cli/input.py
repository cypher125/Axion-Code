"""Interactive input handling with styled textarea-like input box.

The input area looks like a bordered text box with a thick blinking cursor,
similar to Claude Code's terminal UI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.cursor_shapes import CursorShape
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.styles import Style

# ---------------------------------------------------------------------------
# Slash command completer
# ---------------------------------------------------------------------------

SLASH_COMMANDS = [
    "/help", "/quit", "/exit", "/q", "/clear", "/cost", "/status",
    "/model", "/permissions", "/compact", "/config", "/mcp", "/plugins",
    "/skills", "/agents", "/memory", "/init", "/doctor", "/resume",
    "/version", "/sandbox", "/diff", "/export", "/session", "/login",
    "/logout", "/plan",
]

MODEL_COMPLETIONS = [
    "opus", "sonnet", "haiku",
    "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5",
    "gpt-4o", "gpt-4-turbo", "o1", "o3",
    "grok-2", "llama3.1", "mistral",
]

PERMISSION_COMPLETIONS = [
    "read-only", "workspace-write", "danger-full-access", "prompt", "allow",
]


class SlashCommandCompleter(Completer):
    """Context-aware completer for slash commands and their arguments."""

    def get_completions(self, document: Document, complete_event: Any) -> list[Completion]:
        text = document.text_before_cursor.lstrip()

        if not text.startswith("/"):
            return []

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()

        if len(parts) == 1 and not text.endswith(" "):
            return self._complete_command_name(cmd)

        arg_text = parts[1] if len(parts) > 1 else ""
        return self._complete_arguments(cmd, arg_text)

    def _complete_command_name(self, partial: str) -> list[Completion]:
        completions = []
        for cmd in SLASH_COMMANDS:
            if cmd.startswith(partial):
                completions.append(Completion(cmd, start_position=-len(partial)))
        return completions

    def _complete_arguments(self, cmd: str, arg_text: str) -> list[Completion]:
        candidates: list[str] = []

        if cmd == "/model":
            candidates = MODEL_COMPLETIONS
        elif cmd == "/permissions":
            candidates = PERMISSION_COMPLETIONS
        elif cmd == "/mcp":
            candidates = ["list", "show", "help"]
        elif cmd == "/plugins":
            candidates = ["list", "install", "enable", "disable", "uninstall"]
        elif cmd == "/session":
            candidates = ["list", "show", "fork", "switch", "delete", "new"]
        elif cmd == "/plan":
            candidates = ["execute", "exit", "status"]
        elif cmd == "/resume":
            candidates = ["latest"]
        else:
            return []

        completions = []
        for c in candidates:
            if c.startswith(arg_text.lower()):
                completions.append(Completion(c, start_position=-len(arg_text)))
        return completions


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------

def create_key_bindings() -> KeyBindings:
    """Create custom key bindings for the REPL."""
    bindings = KeyBindings()

    @bindings.add(Keys.ControlD)
    def exit_handler(event: Any) -> None:
        event.app.exit(exception=EOFError())

    @bindings.add(Keys.Escape, Keys.Enter)
    def newline_handler(event: Any) -> None:
        event.current_buffer.insert_text("\n")

    return bindings


# ---------------------------------------------------------------------------
# Styled input — textarea-like box with thick cursor
# ---------------------------------------------------------------------------

AXION_INPUT_STYLE = Style.from_dict({
    # Prompt text
    "prompt": "bold cyan",
    "prompt.label": "bold cyan",

    # Input text area — looks like a bordered box
    "": "fg:white",

    # Bottom toolbar
    "bottom-toolbar": "bg:#333333 fg:#888888",
    "bottom-toolbar.text": "fg:#888888",

    # Cursor — block style (thick)
    "cursor-column": "bg:cyan",
})


# ---------------------------------------------------------------------------
# Input session with textarea styling
# ---------------------------------------------------------------------------

class InputSession:
    """Manages the REPL input with a textarea-like bordered appearance.

    Features:
    - Bordered input area that looks like a text editor
    - Block (thick) cursor instead of thin line
    - Tab completion for slash commands
    - History with arrow keys
    - Ctrl+D to exit, Alt+Enter for newline
    """

    def __init__(
        self,
        history_path: Path | None = None,
        multiline: bool = False,
    ) -> None:
        history = FileHistory(str(history_path)) if history_path else None
        self._bindings = create_key_bindings()

        self.session: PromptSession[str] = PromptSession(
            history=history,
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
            key_bindings=self._bindings,
            style=AXION_INPUT_STYLE,
            multiline=multiline,
            cursor=CursorShape.BLOCK,
            prompt_continuation="  ... ",
        )

    async def prompt(self, prompt_text: str = "> ") -> str | None:
        """Get input from the user with textarea styling.

        Returns None on EOF/interrupt.
        """
        try:
            # Build the prompt with a box-like appearance
            prompt_html = HTML(
                f'<prompt>╭─ <prompt.label>{prompt_text.strip()}</prompt.label> '
                f'─────────────────────────────────────────╮\n'
                f'│ </prompt>'
            )
            result = await self.session.prompt_async(
                prompt_html,
                rprompt=HTML('<prompt>│</prompt>'),
            )
            return result
        except (EOFError, KeyboardInterrupt):
            return None

    def push_history(self, text: str) -> None:
        if self.session.history:
            self.session.history.append_string(text)

    @staticmethod
    def default_history_path() -> Path:
        history_dir = Path.home() / ".axion"
        history_dir.mkdir(parents=True, exist_ok=True)
        return history_dir / "repl_history"
