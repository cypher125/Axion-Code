"""Skill slash command handler.

Maps to: rust/crates/commands/src/lib.rs (handle_skills_slash_command)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class SkillSummary:
    name: str
    description: str
    path: str


def handle_skills_command(args: str, cwd: Path | None = None) -> str:
    """Handle /skills [list] command."""
    actual_cwd = cwd or Path.cwd()

    skills = discover_skills(actual_cwd)
    if not skills:
        return "No skills found."

    lines = ["Available skills:", ""]
    for skill in skills:
        lines.append(f"  /{skill.name} — {skill.description}")
    return "\n".join(lines)


def discover_skills(cwd: Path) -> list[SkillSummary]:
    """Discover skill definitions in the project."""
    skills: list[SkillSummary] = []

    # Check .axion/skills/ first, .claude/skills/ for backwards compat
    skills_dir = cwd / ".axion" / "skills"
    if not skills_dir.exists():
        skills_dir = cwd / ".claude" / "skills"
    if skills_dir.exists():
        for f in skills_dir.iterdir():
            if f.suffix == ".md":
                skills.append(SkillSummary(
                    name=f.stem,
                    description=f"Skill defined in {f.name}",
                    path=str(f),
                ))

    # Check .claude/commands/ (legacy)
    commands_dir = cwd / ".claude" / "commands"
    if commands_dir.exists():
        for f in commands_dir.iterdir():
            if f.suffix == ".md":
                skills.append(SkillSummary(
                    name=f.stem,
                    description=f"Skill from commands/{f.name}",
                    path=str(f),
                ))

    return skills
