"""Interactive input handling with prompt_toolkit: completion, multiline, keybindings.

Maps to: rust/crates/rusty-claude-cli/src/input.rs
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion, WordCompleter
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
    "/logout", "/vim", "/fast", "/theme", "/voice", "/branch",
    "/rewind", "/hooks", "/context", "/output-style", "/effort",
    "/plan", "/review", "/tasks", "/commit", "/bughunter",
    "/share", "/feedback", "/upgrade", "/stats", "/files",
    "/summary", "/desktop", "/brief", "/verbose",
]

MODEL_COMPLETIONS = [
    "opus", "sonnet", "haiku",
    "claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5-20251213",
    "gpt-4o", "gpt-4-turbo", "o1", "o3",
    "grok-2",
]

PERMISSION_COMPLETIONS = [
    "read-only", "workspace-write", "danger-full-access", "prompt", "allow",
]


class SlashCommandCompleter(Completer):
    """Context-aware completer for slash commands and their arguments.

    Provides completions for:
    - Command names (with fuzzy matching)
    - /model arguments (model names)
    - /permissions arguments (permission modes)
    - /mcp arguments (list, show, help)
    - /plugins arguments (list, install, enable, disable, uninstall)
    - /session arguments (list, show, fork, switch, delete)
    """

    def get_completions(self, document: Document, complete_event: Any) -> list[Completion]:
        text = document.text_before_cursor.lstrip()

        if not text.startswith("/"):
            return []

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()

        # If still typing the command name
        if len(parts) == 1 and not text.endswith(" "):
            return self._complete_command_name(cmd)

        # Completing arguments for known commands
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
            candidates = ["list", "show", "fork", "switch", "delete"]
        elif cmd == "/theme":
            candidates = ["dark", "light", "default"]
        elif cmd == "/effort":
            candidates = ["low", "medium", "high"]
        elif cmd in ("/output-style", "/brief", "/verbose"):
            candidates = ["brief", "verbose", "default"]
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
        """Exit on Ctrl+D."""
        event.app.exit(exception=EOFError())

    @bindings.add(Keys.Escape, Keys.Enter)
    def newline_handler(event: Any) -> None:
        """Insert newline on Alt+Enter (for multiline input)."""
        event.current_buffer.insert_text("\n")

    return bindings


# ---------------------------------------------------------------------------
# REPL style
# ---------------------------------------------------------------------------

REPL_STYLE = Style.from_dict({
    "prompt": "bold cyan",
    "": "",  # default text
})


# ---------------------------------------------------------------------------
# Input session
# ---------------------------------------------------------------------------

class InputSession:
    """Manages the REPL input session with history, completion, and key bindings.

    Maps to: rust/crates/rusty-claude-cli/src/input.rs::SlashCommandHelper
    """

    def __init__(
        self,
        history_path: Path | None = None,
        multiline: bool = False,
    ) -> None:
        history = FileHistory(str(history_path)) if history_path else None
        self._bindings = create_key_bindings()
        self._multiline = multiline

        self.session: PromptSession[str] = PromptSession(
            history=history,
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
            key_bindings=self._bindings,
            style=REPL_STYLE,
            multiline=multiline,
        )

    async def prompt(self, prompt_text: str = "axion> ") -> str | None:
        """Get input from the user. Returns None on EOF/interrupt."""
        try:
            result = await self.session.prompt_async(
                HTML(f"<prompt>{prompt_text}</prompt>"),
            )
            return result
        except (EOFError, KeyboardInterrupt):
            return None

    def push_history(self, text: str) -> None:
        """Manually add an entry to history."""
        if self.session.history:
            self.session.history.append_string(text)

    def set_multiline(self, enabled: bool) -> None:
        """Toggle multiline input mode."""
        self._multiline = enabled
        # Note: prompt_toolkit doesn't support changing multiline on existing session
        # This would require recreating the session

    @staticmethod
    def default_history_path() -> Path:
        """Get the default history file path."""
        history_dir = Path.home() / ".axion"
        history_dir.mkdir(parents=True, exist_ok=True)
        return history_dir / "repl_history"
