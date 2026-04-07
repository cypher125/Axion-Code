"""Extract TypeScript manifests from upstream repo.

Maps to: rust/crates/compat-harness/src/lib.rs
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UpstreamPaths:
    """Resolver for upstream repo file paths."""

    repo_root: Path

    def commands_path(self) -> Path:
        return self.repo_root / "src" / "commands.ts"

    def tools_path(self) -> Path:
        return self.repo_root / "src" / "tools.ts"

    def cli_path(self) -> Path:
        return self.repo_root / "src" / "entrypoints" / "cli.tsx"

    @classmethod
    def from_repo_root(cls, root: Path) -> UpstreamPaths:
        return cls(repo_root=root)

    @classmethod
    def from_workspace_dir(cls, directory: Path) -> UpstreamPaths | None:
        """Auto-discover upstream repo from workspace directory."""
        candidates = _upstream_repo_candidates(directory)
        for candidate in candidates:
            if (candidate / "src" / "commands.ts").exists():
                return cls(repo_root=candidate)
        return None


@dataclass
class ExtractedManifest:
    """Parsed manifests from upstream TypeScript."""

    commands: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    bootstrap_phases: list[str] = field(default_factory=list)


def extract_manifest(paths: UpstreamPaths) -> ExtractedManifest:
    """Read and parse all upstream manifest files."""
    manifest = ExtractedManifest()

    # Extract commands
    commands_path = paths.commands_path()
    if commands_path.exists():
        source = commands_path.read_text(encoding="utf-8")
        manifest.commands = extract_commands(source)

    # Extract tools
    tools_path = paths.tools_path()
    if tools_path.exists():
        source = tools_path.read_text(encoding="utf-8")
        manifest.tools = extract_tools(source)

    # Extract bootstrap phases
    cli_path = paths.cli_path()
    if cli_path.exists():
        source = cli_path.read_text(encoding="utf-8")
        manifest.bootstrap_phases = extract_bootstrap_plan(source)

    return manifest


def extract_commands(source: str) -> list[str]:
    """Parse command names from TypeScript imports and feature gates."""
    commands: list[str] = []
    for line in source.splitlines():
        # Match import { X } from './commands/X'
        match = re.search(r"import\s*\{([^}]+)\}", line)
        if match:
            symbols = [s.strip() for s in match.group(1).split(",")]
            commands.extend(s for s in symbols if s)

        # Match feature('name', ...)
        match = re.search(r"feature\(['\"]([^'\"]+)['\"]", line)
        if match:
            commands.append(match.group(1))

    return sorted(set(commands))


def extract_tools(source: str) -> list[str]:
    """Parse tool names from TypeScript imports."""
    tools: list[str] = []
    for line in source.splitlines():
        match = re.search(r"import\s*\{([^}]+)\}", line)
        if match:
            symbols = [s.strip() for s in match.group(1).split(",")]
            for s in symbols:
                if s.endswith("Tool"):
                    tools.append(s)
    return sorted(set(tools))


def extract_bootstrap_plan(source: str) -> list[str]:
    """Detect bootstrap phases from CLI entry point."""
    phases: list[str] = []
    markers = {
        "--version": "version_check",
        "profiler": "profiler",
        "system-prompt": "system_prompt",
        "daemon": "daemon",
    }
    for line in source.splitlines():
        for marker, phase in markers.items():
            if marker in line:
                phases.append(phase)
    return list(dict.fromkeys(phases))  # Dedupe preserving order


def _upstream_repo_candidates(primary: Path) -> list[Path]:
    """Find candidate upstream repo locations."""
    candidates: list[Path] = []

    # Check environment variable
    env_root = os.environ.get("CLAUDE_CODE_UPSTREAM")
    if env_root:
        candidates.append(Path(env_root))

    # Check parent directories
    current = primary
    for _ in range(5):
        candidates.append(current)
        parent = current.parent
        if parent == current:
            break
        current = parent

    # Check vendor directories
    candidates.append(primary / "vendor" / "claude-code")

    return candidates
