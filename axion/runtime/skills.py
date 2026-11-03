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

# Directories searched (relative to cwd) when resolving a skill by name. Also checked under the
# user's home so global skills work anywhere.
_SKILL_SEARCH_DIRS: list[str] = [
    ".axion/skills", ".claude/skills",
    ".axion/commands", ".claude/commands",
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


def _skill_dirs(cwd: Path) -> list[Path]:
    dirs = [cwd / d for d in _SKILL_SEARCH_DIRS]
    dirs += [Path.home() / ".axion" / "skills", Path.home() / ".claude" / "skills"]
    return dirs


def resolve_skill(name: str, cwd: Path) -> Path | None:
    """Find a skill file matching *name* in the project and home skill dirs (or None)."""
    for base in _skill_dirs(cwd):
        candidate = base / f"{name}.md"
        if candidate.is_file():
            return candidate
        candidate = base / name
        if candidate.is_file():
            return candidate
    return None


def list_skills(cwd: Path) -> list[SkillDefinition]:
    """Load every skill found in the project and home skill directories (deduped by name)."""
    out: dict[str, SkillDefinition] = {}
    for base in _skill_dirs(cwd):
        if not base.is_dir():
            continue
        for f in sorted(base.glob("*.md")):
            try:
                skill = load_skill(f)
            except OSError:
                continue
            out.setdefault(skill.name, skill)
    return list(out.values())


def render_skills_for_prompt(cwd: Path, max_chars: int = 1500) -> str:
    """A system-prompt section listing available skills, so the model knows it can invoke them."""
    skills = list_skills(cwd)
    if not skills:
        return ""
    lines = [
        "# Skills",
        "",
        "Reusable procedures available via the Skill tool (or as /<name> slash commands). Invoke one "
        "with the Skill tool when its description matches the task:",
        "",
    ]
    for s in skills:
        lines.append(f"- {s.name}: {s.description}" if s.description else f"- {s.name}")
    text = "\n".join(lines)
    return text[:max_chars] + ("\n..." if len(text) > max_chars else "")


def execute_skill(skill: SkillDefinition, user_args: str) -> str:
    """Expand a skill's body: substitute {{args}}, $ARGUMENTS, and positional $1..$9 from user_args."""
    result = skill.content
    result = result.replace("{{args}}", user_args).replace("$ARGUMENTS", user_args)
    parts = user_args.split()
    for i in range(9, 0, -1):  # $9 down to $1 so $10 isn't clobbered by $1
        result = result.replace(f"${i}", parts[i - 1] if i - 1 < len(parts) else "")
    return result
