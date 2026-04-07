"""Repository initialization command.

Maps to: rust/crates/rusty-claude-cli/src/init.rs
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console


def init_project(cwd: Path | None = None, console: Console | None = None) -> None:
    """Initialize a new project with CLAUDE.md."""
    actual_cwd = cwd or Path.cwd()
    con = console or Console()

    claude_md = actual_cwd / "CLAUDE.md"
    if claude_md.exists():
        con.print("[yellow]CLAUDE.md already exists[/yellow]")
        return

    # Create .axion directory
    axion_dir = actual_cwd / ".axion"
    axion_dir.mkdir(exist_ok=True)

    # Create CLAUDE.md
    claude_md.write_text(
        "# CLAUDE.md\n\n"
        "This file provides guidance to Claude Code when working with this codebase.\n\n"
        "## Project overview\n\n"
        "<!-- Describe your project here -->\n\n"
        "## Build & test\n\n"
        "<!-- Add build and test commands -->\n\n"
        "## Code conventions\n\n"
        "<!-- Add coding style guidelines -->\n",
        encoding="utf-8",
    )
    con.print("[green]Created CLAUDE.md[/green]")

    # Create .axion/settings.json if it doesn't exist
    settings = axion_dir / "settings.json"
    if not settings.exists():
        settings.write_text('{\n  "permissions": {\n    "defaultMode": "prompt"\n  }\n}\n')
        con.print("[green]Created .axion/settings.json[/green]")
