"""Interactive input with fixed bottom toolbar and clean prompt.

Simple, reliable approach:
- Clean prompt (no box-drawing — they break with line wrapping)
- Fixed bottom toolbar showing model, tokens, cost
- Block cursor
- Tab completion for slash commands
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
    "gpt-4o", "o1", "o3", "grok-2", "llama3.1", "mistral",
]


class SlashCommandCompleter(Completer):
    """Context-aware completer for slash commands."""

    def get_completions(self, document: Document, complete_event: Any) -> list[Completion]:
        text = document.text_before_cursor.lstrip()
        if not text.startswith("/"):
            return []

        parts = text.split(maxsplit=1)
        cmd = parts[0].lower()

        if len(parts) == 1 and not text.endswith(" "):
            return [
                Completion(c, start_position=-len(cmd))
                for c in SLASH_COMMANDS if c.startswith(cmd)
            ]

        arg_text = parts[1] if len(parts) > 1 else ""
        candidates: list[str] = []
        if cmd == "/model":
            candidates = MODEL_COMPLETIONS
        elif cmd == "/session":
            candidates = ["list", "show", "fork", "switch", "delete", "new"]
        elif cmd == "/plan":
            candidates = ["execute", "exit", "status"]
        elif cmd == "/plugins":
            candidates = ["list", "install", "enable", "disable"]
        elif cmd == "/resume":
            candidates = ["latest"]

        return [
            Completion(c, start_position=-len(arg_text))
            for c in candidates if c.startswith(arg_text.lower())
        ]


# ---------------------------------------------------------------------------
# Key bindings
# ---------------------------------------------------------------------------

def create_key_bindings() -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add(Keys.ControlD)
    def _(event: Any) -> None:
        event.app.exit(exception=EOFError())

    return bindings


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

# Navy/Cyan terminal theme
INPUT_STYLE = Style.from_dict({
    "prompt": "#00d4aa bold",                          # Teal prompt
    "bottom-toolbar": "bg:#0a192f fg:#8892b0",         # Navy bg, muted text
    "bottom-toolbar.text": "bg:#0a192f fg:#8892b0",
    "placeholder": "#4a5568",                           # Dark gray placeholder
})


# ---------------------------------------------------------------------------
# Input session
# ---------------------------------------------------------------------------

class InputSession:
    """Clean input with fixed bottom toolbar showing live stats."""

    def __init__(self, history_path: Path | None = None) -> None:
        history = FileHistory(str(history_path)) if history_path else None

        self._status_model = ""
        self._status_tokens = 0
        self._status_cost = 0.0
        self._status_turn = 0

        self.session: PromptSession[str] = PromptSession(
            history=history,
            completer=SlashCommandCompleter(),
            complete_while_typing=True,
            key_bindings=create_key_bindings(),
            style=INPUT_STYLE,
            cursor=CursorShape.BLOCK,
            bottom_toolbar=self._toolbar,
        )

    def _toolbar(self) -> HTML:
        """Build the fixed bottom toolbar content."""
        if self._status_turn == 0:
            return HTML(
                " <b>axion</b> │ /help for commands │ Ctrl+C to interrupt"
            )
        return HTML(
            f" <b>{self._status_model}</b>"
            f" │ turn {self._status_turn}"
            f" │ {self._status_tokens:,} tokens"
            f" │ ${self._status_cost:.4f}"
        )

    def update_status(self, model: str, tokens: int, cost: float, turn: int) -> None:
        """Update toolbar data (called after each turn)."""
        self._status_model = model
        self._status_tokens = tokens
        self._status_cost = cost
        self._status_turn = turn

    async def prompt(self, prompt_text: str = "axion") -> str | None:
        """Get input with a clean prompt, placeholder hint, and fixed toolbar."""
        import random

        placeholders = [
            "Try: fix the bug in main.py",
            "Try: explain this codebase",
            "Try: add tests for the API",
            "Try: search for TODO comments",
            "Try: read README.md and summarize",
            "Try: /plan add authentication",
            "Try: /help for all commands",
        ]
        hint = random.choice(placeholders)

        try:
            result = await self.session.prompt_async(
                HTML(f"<prompt>{prompt_text} &gt; </prompt>"),
                placeholder=HTML(f"<style bg='' fg='#555555'>{hint}</style>"),
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
