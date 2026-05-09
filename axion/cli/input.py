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
from prompt_toolkit.completion import Completer, Completion, merge_completers
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

def _get_slash_commands() -> list[str]:
    """Get all slash commands from the registry (always up to date)."""
    from axion.commands.registry import get_command_registry
    reg = get_command_registry()
    return [f"/{name}" for name in reg.command_names()]

MODEL_COMPLETIONS = [
    # Anthropic
    "opus", "sonnet", "haiku",
    # OpenAI GPT-4
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano",
    # OpenAI GPT-5
    "gpt-5", "gpt-5-mini", "gpt-5-nano", "gpt-5-pro", "gpt-5.4", "gpt-5.4-mini",
    # OpenAI Codex
    "codex", "gpt-5-codex",
    # OpenAI reasoning
    "o1", "o3", "o3-mini", "o3-pro", "o4-mini",
    # xAI
    "grok-2", "grok-3",
    # Local (Ollama)
    "llama3.1", "llama4", "mistral", "codellama", "deepseek", "phi", "gemma", "qwen",
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
                for c in _get_slash_commands() if c.startswith(cmd)
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
        elif cmd == "/mcp":
            candidates = ["list", "show", "help"]
        elif cmd == "/permissions":
            candidates = ["allow", "prompt", "read-only", "workspace-write"]
        elif cmd == "/share":
            candidates = ["file", "json", "import"]
        elif cmd == "/undo":
            candidates = ["hard"]
        elif cmd == "/init-project" or cmd == "/scaffold":
            candidates = ["react", "nextjs", "django", "fastapi", "express", "cli", "flask"]
        elif cmd == "/export":
            candidates = ["transcript.md"]

        return [
            Completion(c, start_position=-len(arg_text))
            for c in candidates if c.startswith(arg_text.lower())
        ]


class FileTagCompleter(Completer):
    """Completer for @file references — suggests files/dirs in the current or specified directory."""

    def get_completions(self, document: Document, complete_event: Any) -> list[Completion]:
        text_before = document.text_before_cursor

        # Find the last @ token that is either at the start or preceded by whitespace
        at_idx = -1
        for i in range(len(text_before) - 1, -1, -1):
            if text_before[i] == "@" and (i == 0 or text_before[i - 1] in (" ", "\t")):
                at_idx = i
                break

        if at_idx == -1:
            return []

        # The partial path typed after @
        partial = text_before[at_idx + 1:]

        # Determine the directory to list and the prefix to match
        if "/" in partial or "\\" in partial:
            # User typed a partial path like @src/ma — split into dir + prefix
            sep = partial.rfind("/")
            if sep == -1:
                sep = partial.rfind("\\")
            dir_part = partial[: sep + 1]
            name_prefix = partial[sep + 1:]
            search_dir = Path(dir_part) if dir_part else Path(".")
        else:
            dir_part = ""
            name_prefix = partial
            search_dir = Path(".")

        try:
            entries = sorted(search_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except (OSError, PermissionError):
            return []

        completions: list[Completion] = []
        for entry in entries:
            name = entry.name
            # Skip hidden files/dirs
            if name.startswith("."):
                continue
            if not name.lower().startswith(name_prefix.lower()):
                continue

            display_name = name + "/" if entry.is_dir() else name
            completion_text = dir_part + display_name

            completions.append(
                Completion(
                    completion_text,
                    start_position=-len(partial),
                    display=display_name,
                )
            )

        return completions


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

        combined_completer = merge_completers(
            [SlashCommandCompleter(), FileTagCompleter()]
        )

        self.session: PromptSession[str] = PromptSession(
            history=history,
            completer=combined_completer,
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
        mode = getattr(self, "_status_auth_mode", "")
        model_lc = (self._status_model or "").lower()
        if mode == "subscription":
            # ChatGPT for codex, Pro/Max for Claude
            sub_label = "ChatGPT" if "codex" in model_lc else "Pro/Max"
            cost_part = sub_label
        elif mode == "local":
            cost_part = "local"
        elif mode == "api":
            cost_part = f"API · ${self._status_cost:.4f}"
        else:
            cost_part = f"${self._status_cost:.4f}"
        return HTML(
            f" <b>{self._status_model}</b>"
            f" │ turn {self._status_turn}"
            f" │ {self._status_tokens:,} tokens"
            f" │ {cost_part}"
        )

    def update_status(
        self,
        model: str,
        tokens: int,
        cost: float,
        turn: int,
        auth_mode: str = "",
    ) -> None:
        """Update toolbar data (called after each turn)."""
        self._status_model = model
        self._status_tokens = tokens
        self._status_cost = cost
        self._status_turn = turn
        self._status_auth_mode = auth_mode

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
