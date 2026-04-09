"""Skill loading and execution.

Maps to: rust/crates/runtime/src/skills.rs

Skills are .md files with optional YAML frontmatter that define reusable
prompt templates. They can be loaded from several conventional directories
and executed by replacing {{args}} placeholders with user-supplied arguments.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Directories searched (relative to cwd) when resolving a skill by name.
_SKILL_SEARCH_DIRS: list[str] = [
    ".axion/skills", ".claude/skills",
    ".axion/commands", ".claude/commands",
    ".axion/skills",
]


@dataclass
class SkillDefinition:
    """A parsed skill definition."""

    name: str
    description: str
    content: str
    source_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# YAML frontmatter helpers
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)


def _parse_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse simple YAML frontmatter between --- delimiters.

    Returns (metadata_dict, remaining_content).  Uses a lightweight
    key: value parser so we avoid a hard dependency on PyYAML.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    yaml_block = match.group(1)
    body = match.group(2)

    metadata: dict[str, Any] = {}
    for line in yaml_block.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            metadata[key.strip()] = value.strip()

    return metadata, body


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_skill(path: Path) -> SkillDefinition:
    """Read a .md skill file, parse YAML frontmatter, and return a SkillDefinition."""
    text = path.read_text(encoding="utf-8")
    metadata, content = _parse_yaml_frontmatter(text)

    name = metadata.get("name", path.stem)
    description = metadata.get("description", "")

    return SkillDefinition(
        name=name,
        description=description,
        content=content.strip(),
        source_path=path,
        metadata=metadata,
    )


def resolve_skill(name: str, cwd: Path) -> Path | None:
    """Search conventional directories for a skill file matching *name*.

    Searches .claude/skills/, .claude/commands/, .axion/skills/ under *cwd*.
    Returns the first matching .md file, or ``None``.
    """
    for search_dir in _SKILL_SEARCH_DIRS:
        base = cwd / search_dir

        # Try exact name with .md extension
        candidate = base / f"{name}.md"
        if candidate.is_file():
            return candidate

        # Try name as-is (may already include extension)
        candidate = base / name
        if candidate.is_file():
            return candidate

    return None


def execute_skill(skill: SkillDefinition, user_args: str) -> str:
    """Execute a skill by replacing ``{{args}}`` with *user_args*.

    Returns the skill content with placeholders substituted.
    """
    result = skill.content.replace("{{args}}", user_args)
    return result
