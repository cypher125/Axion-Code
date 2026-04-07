"""Persistent memory system.

Maps to: rust/crates/runtime/src/memory.rs

Provides a file-backed memory store where entries are saved as .md files
with YAML frontmatter.  An index file (MEMORY.md) tracks all entries.
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_MEMORY_DIR = Path.home() / ".axion" / "memory"

# Reuse the lightweight frontmatter parser from skills
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)",
    re.DOTALL,
)


class MemoryType(enum.Enum):
    USER = "user"
    FEEDBACK = "feedback"
    PROJECT = "project"
    REFERENCE = "reference"


@dataclass
class MemoryEntry:
    """A single memory entry."""

    name: str
    description: str
    type: MemoryType
    content: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text
    meta: dict[str, str] = {}
    for line in match.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, match.group(2)


def _build_frontmatter(entry: MemoryEntry) -> str:
    lines = [
        "---",
        f"name: {entry.name}",
        f"description: {entry.description}",
        f"type: {entry.type.value}",
        f"created_at: {entry.created_at}",
        f"updated_at: {entry.updated_at}",
        "---",
        "",
        entry.content,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------


class MemoryStore:
    """File-backed memory store.

    Each entry is stored as a .md file under *memory_dir*.  An index
    file (MEMORY.md) provides a human-readable listing.
    """

    def __init__(self, memory_dir: Path | None = None) -> None:
        self.memory_dir = memory_dir or _DEFAULT_MEMORY_DIR

    def _ensure_dir(self) -> None:
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def _entry_path(self, name: str) -> Path:
        safe_name = re.sub(r"[^\w\-.]", "_", name)
        return self.memory_dir / f"{safe_name}.md"

    # -- CRUD ---------------------------------------------------------------

    def save(self, entry: MemoryEntry) -> Path:
        """Write an entry as a .md file with YAML frontmatter."""
        self._ensure_dir()
        entry.updated_at = datetime.now(timezone.utc).isoformat()
        path = self._entry_path(entry.name)
        path.write_text(_build_frontmatter(entry), encoding="utf-8")
        logger.debug("Saved memory entry '%s' to %s", entry.name, path)
        return path

    def load(self, name: str) -> MemoryEntry | None:
        """Read a single memory file by name."""
        path = self._entry_path(name)
        if not path.is_file():
            return None
        return self._read_entry(path)

    def load_all(self) -> list[MemoryEntry]:
        """Read all memory files in the store."""
        if not self.memory_dir.is_dir():
            return []
        entries: list[MemoryEntry] = []
        for path in sorted(self.memory_dir.glob("*.md")):
            if path.name == "MEMORY.md":
                continue
            entry = self._read_entry(path)
            if entry is not None:
                entries.append(entry)
        return entries

    def remove(self, name: str) -> bool:
        """Delete a memory file. Returns True if the file existed."""
        path = self._entry_path(name)
        if path.is_file():
            path.unlink()
            logger.debug("Removed memory entry '%s'", name)
            return True
        return False

    # -- Index --------------------------------------------------------------

    def load_index(self) -> str | None:
        """Read the MEMORY.md index file."""
        index_path = self.memory_dir / "MEMORY.md"
        if index_path.is_file():
            return index_path.read_text(encoding="utf-8")
        return None

    def save_index(self, entries: list[MemoryEntry] | None = None) -> Path:
        """Write a MEMORY.md index listing all entries."""
        self._ensure_dir()
        if entries is None:
            entries = self.load_all()

        lines = ["# Memory Index", ""]
        for entry in entries:
            lines.append(
                f"- **{entry.name}** ({entry.type.value}): {entry.description}"
            )
        lines.append("")

        index_path = self.memory_dir / "MEMORY.md"
        index_path.write_text("\n".join(lines), encoding="utf-8")
        logger.debug("Saved memory index with %d entries", len(entries))
        return index_path

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _read_entry(path: Path) -> MemoryEntry | None:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read memory file %s: %s", path, exc)
            return None

        meta, content = _parse_frontmatter(text)

        try:
            mem_type = MemoryType(meta.get("type", "reference"))
        except ValueError:
            mem_type = MemoryType.REFERENCE

        return MemoryEntry(
            name=meta.get("name", path.stem),
            description=meta.get("description", ""),
            type=mem_type,
            content=content.strip(),
            created_at=meta.get("created_at", ""),
            updated_at=meta.get("updated_at", ""),
        )
