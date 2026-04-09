"""Agent slash command handler.

Maps to: rust/crates/commands/src/lib.rs (handle_agents_slash_command)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class AgentSummary:
    name: str
    description: str
    path: str


def handle_agents_command(args: str, cwd: Path | None = None) -> str:
    """Handle /agents [list] command."""
    actual_cwd = cwd or Path.cwd()

    agents = discover_agents(actual_cwd)
    if not agents:
        return "No agents found."

    lines = ["Available agents:", ""]
    for agent in agents:
        lines.append(f"  {agent.name} — {agent.description}")
        lines.append(f"    Path: {agent.path}")
    return "\n".join(lines)


def discover_agents(cwd: Path) -> list[AgentSummary]:
    """Discover agent definitions in the project."""
    agents: list[AgentSummary] = []

    # Check .axion/agents/ first, .claude/agents/ for backwards compat
    agents_dir = cwd / ".axion" / "agents"
    if not agents_dir.exists():
        agents_dir = cwd / ".claude" / "agents"
    if agents_dir.exists():
        for f in agents_dir.iterdir():
            if f.suffix == ".md":
                agents.append(AgentSummary(
                    name=f.stem,
                    description=f"Agent defined in {f.name}",
                    path=str(f),
                ))

    return agents
