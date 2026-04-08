"""Repository initialization command — creates AXION.md."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console


def init_project(cwd: Path | None = None, console: Console | None = None) -> None:
    """Initialize a new project with AXION.md and .axion/ directory."""
    actual_cwd = cwd or Path.cwd()
    con = console or Console()

    # Check for existing instruction files
    axion_md = actual_cwd / "AXION.md"
    claude_md = actual_cwd / "CLAUDE.md"

    if axion_md.exists():
        con.print("[yellow]AXION.md already exists[/yellow]")
        return
    if claude_md.exists():
        con.print("[yellow]CLAUDE.md found — rename to AXION.md? (Axion reads both)[/yellow]")
        return

    # Create .axion directory
    axion_dir = actual_cwd / ".axion"
    axion_dir.mkdir(exist_ok=True)

    # Create AXION.md
    axion_md.write_text(
        "# AXION.md\n\n"
        "This file provides guidance to Axion Code when working with this codebase.\n\n"
        "## Project overview\n\n"
        "<!-- Describe your project here -->\n\n"
        "## Build & test\n\n"
        "<!-- Add build and test commands -->\n\n"
        "## Code conventions\n\n"
        "<!-- Add coding style guidelines -->\n",
        encoding="utf-8",
    )
    con.print("[green]Created AXION.md[/green]")

    # Create .axion/settings.json if it doesn't exist
    settings = axion_dir / "settings.json"
    if not settings.exists():
        settings.write_text(
            '{\n  "permissions": {\n    "defaultMode": "prompt"\n  }\n}\n'
        )
        con.print("[green]Created .axion/settings.json[/green]")
