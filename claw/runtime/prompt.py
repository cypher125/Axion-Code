"""System prompt assembly.

Maps to: rust/crates/runtime/src/prompt.rs
"""

from __future__ import annotations

import os
import platform
import subprocess
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

FRONTIER_MODEL_NAME = "Claude Opus 4.6"
SYSTEM_PROMPT_DYNAMIC_BOUNDARY = "__SYSTEM_PROMPT_DYNAMIC_BOUNDARY__"


@dataclass
class ProjectContext:
    """Context about the current project/working directory."""

    cwd: Path = field(default_factory=Path.cwd)
    current_date: str = field(default_factory=lambda: date.today().isoformat())
    git_status: str | None = None
    git_diff: str | None = None
    instruction_files: list[str] = field(default_factory=list)


@dataclass
class SystemPromptBuilder:
    """Builds the system prompt for the conversation.

    Maps to: rust/crates/runtime/src/prompt.rs::SystemPromptBuilder
    """

    project_context: ProjectContext = field(default_factory=ProjectContext)
    model_name: str = FRONTIER_MODEL_NAME
    os_name: str = field(default_factory=lambda: platform.system())
    os_version: str = field(default_factory=lambda: platform.version())
    append_sections: list[str] = field(default_factory=list)

    def build(self) -> str:
        """Assemble the complete system prompt."""
        sections: list[str] = []

        # Core identity
        sections.append(
            f"You are Claude Code, an interactive CLI agent that helps users with "
            f"software engineering tasks. Use the instructions below and the tools "
            f"available to you to assist the user."
        )

        # Environment info
        sections.append(self._environment_section())

        # Project context
        if self.project_context.instruction_files:
            for content in self.project_context.instruction_files:
                sections.append(content)

        # Additional sections
        sections.extend(self.append_sections)

        return "\n\n".join(sections)

    def _environment_section(self) -> str:
        ctx = self.project_context
        lines = [
            "# Environment",
            f"- Working directory: {ctx.cwd}",
            f"- Platform: {self.os_name}",
            f"- Date: {ctx.current_date}",
        ]
        if ctx.git_status:
            lines.append(f"- Git status: {ctx.git_status}")
        return "\n".join(lines)

    @classmethod
    def for_cwd(cls, cwd: Path | None = None) -> SystemPromptBuilder:
        """Create a prompt builder with auto-detected project context."""
        actual_cwd = cwd or Path.cwd()
        ctx = ProjectContext(cwd=actual_cwd)

        # Try to load CLAUDE.md
        claude_md = actual_cwd / "CLAUDE.md"
        if claude_md.exists():
            try:
                ctx.instruction_files.append(claude_md.read_text(encoding="utf-8"))
            except OSError:
                pass

        # Try to get git status
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                capture_output=True,
                text=True,
                cwd=str(actual_cwd),
                timeout=5,
            )
            if result.returncode == 0:
                ctx.git_status = result.stdout.strip() or "(clean)"
        except (subprocess.SubprocessError, FileNotFoundError):
            pass

        return cls(project_context=ctx)
