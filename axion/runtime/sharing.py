"""Session sharing — export a session as a shareable link or file.

Sharing modes:
1. File export: /share file → creates a .axion-share file that others can import
2. JSON export: /share json → outputs a portable JSON blob
3. Link (future): /share link → uploads to a server and returns a URL
"""

from __future__ import annotations

import base64
import json
import time
import zlib
from dataclasses import dataclass
from pathlib import Path

from axion.runtime.session import Session


@dataclass
class SharedSession:
    """A portable session snapshot for sharing."""

    session_id: str
    messages_count: int
    created_at_ms: int
    shared_at_ms: int
    shared_by: str
    data: str  # Compressed, base64-encoded session JSON


def export_session_for_sharing(
    session: Session,
    shared_by: str = "",
) -> SharedSession:
    """Export a session as a shareable snapshot."""
    # Serialize session to JSON
    session_dict = session._to_dict()
    session_json = json.dumps(session_dict, separators=(",", ":"))

    # Compress and encode
    compressed = zlib.compress(session_json.encode("utf-8"))
    encoded = base64.b64encode(compressed).decode("ascii")

    return SharedSession(
        session_id=session.session_id,
        messages_count=session.message_count(),
        created_at_ms=session.created_at_ms,
        shared_at_ms=int(time.time() * 1000),
        shared_by=shared_by,
        data=encoded,
    )


def import_shared_session(shared: SharedSession) -> Session:
    """Import a shared session snapshot."""
    # Decode and decompress
    compressed = base64.b64decode(shared.data)
    session_json = zlib.decompress(compressed).decode("utf-8")
    session_dict = json.loads(session_json)

    return Session._from_dict(session_dict)


def save_share_file(shared: SharedSession, output_path: Path) -> None:
    """Save a shared session to a .axion-share file."""
    data = {
        "version": 1,
        "type": "axion-shared-session",
        "session_id": shared.session_id,
        "messages_count": shared.messages_count,
        "created_at_ms": shared.created_at_ms,
        "shared_at_ms": shared.shared_at_ms,
        "shared_by": shared.shared_by,
        "data": shared.data,
    }
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_share_file(input_path: Path) -> SharedSession:
    """Load a shared session from a .axion-share file."""
    raw = json.loads(input_path.read_text(encoding="utf-8"))

    if raw.get("type") != "axion-shared-session":
        raise ValueError(f"Not a valid Axion share file: {input_path}")

    return SharedSession(
        session_id=raw["session_id"],
        messages_count=raw["messages_count"],
        created_at_ms=raw["created_at_ms"],
        shared_at_ms=raw["shared_at_ms"],
        shared_by=raw.get("shared_by", ""),
        data=raw["data"],
    )


def handle_share_command(args: str, session: Session) -> str:
    """Handle /share [file|json|import <path>].

    Usage:
        /share file           — save as .axion-share file
        /share file out.share — save with custom name
        /share json           — print as JSON blob
        /share import file.axion-share — import a shared session
    """
    parts = args.strip().split(maxsplit=1)
    action = parts[0].lower() if parts else "file"
    target = parts[1].strip() if len(parts) > 1 else ""

    if action == "file":
        filename = target or f"session-{session.session_id[:8]}.axion-share"
        output_path = Path.cwd() / filename
        shared = export_session_for_sharing(session)
        save_share_file(shared, output_path)
        return (
            f"Session shared to: {output_path}\n"
            f"  Messages: {shared.messages_count}\n"
            f"  Size: {output_path.stat().st_size:,} bytes\n\n"
            f"Send this file to a teammate. They can import with:\n"
            f"  /share import {filename}"
        )

    if action == "json":
        shared = export_session_for_sharing(session)
        blob = json.dumps({
            "session_id": shared.session_id,
            "messages": shared.messages_count,
            "data": shared.data[:100] + "...",
        }, indent=2)
        return f"Shared session JSON (truncated):\n{blob}"

    if action == "import":
        if not target:
            return "Usage: /share import <file.axion-share>"
        import_path = Path(target)
        if not import_path.exists():
            return f"File not found: {target}"
        try:
            shared = load_share_file(import_path)
            imported = import_shared_session(shared)
            # Replace current session
            session.messages = imported.messages
            session.session_id = imported.session_id
            session.created_at_ms = imported.created_at_ms
            return (
                f"Imported session {imported.session_id}\n"
                f"  Messages: {imported.message_count()}\n"
                f"  Shared by: {shared.shared_by or 'unknown'}"
            )
        except Exception as exc:
            return f"Import failed: {exc}"

    return (
        "Usage:\n"
        "  /share file [name]  — export session as shareable file\n"
        "  /share json         — export as JSON\n"
        "  /share import <file> — import a shared session"
    )
