"""File operations: read, write, edit, glob search, grep search.

Maps to: rust/crates/runtime/src/file_ops.rs
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Limits matching Rust
MAX_READ_SIZE = 10 * 1024 * 1024  # 10 MiB
MAX_WRITE_SIZE = 10 * 1024 * 1024  # 10 MiB
DEFAULT_HEAD_LIMIT = 250
DEFAULT_GLOB_LIMIT = 100
BINARY_CHECK_SIZE = 8192  # 8 KiB


# ---------------------------------------------------------------------------
# Binary detection
# ---------------------------------------------------------------------------

def is_binary_file(path: Path, check_size: int = BINARY_CHECK_SIZE) -> bool:
    """Check if a file appears to be binary (contains NUL bytes in first 8 KiB)."""
    try:
        with open(path, "rb") as f:
            chunk = f.read(check_size)
            return b"\x00" in chunk
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Workspace boundary validation
# ---------------------------------------------------------------------------

def validate_workspace_boundary(file_path: Path, workspace_root: Path | None = None) -> None:
    """Validate that a file path doesn't escape the workspace boundary."""
    if workspace_root is None:
        return
    try:
        resolved = file_path.resolve()
        root_resolved = workspace_root.resolve()
        if not str(resolved).startswith(str(root_resolved)):
            raise PermissionError(
                f"Path {file_path} escapes workspace boundary {workspace_root}"
            )
    except OSError:
        pass


def is_symlink_escape(path: Path, workspace_root: Path) -> bool:
    """Check if a path is a symlink that escapes the workspace."""
    try:
        if path.is_symlink():
            target = path.resolve()
            root = workspace_root.resolve()
            return not str(target).startswith(str(root))
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Patch generation
# ---------------------------------------------------------------------------

@dataclass
class StructuredPatchHunk:
    old_start: int
    old_lines: int
    new_start: int
    new_lines: int
    lines: list[str]


def make_patch(original: str, modified: str, filename: str = "") -> list[StructuredPatchHunk]:
    """Generate unified diff hunks between original and modified text."""
    orig_lines = original.splitlines(keepends=True)
    mod_lines = modified.splitlines(keepends=True)

    matcher = difflib.SequenceMatcher(None, orig_lines, mod_lines)
    hunks: list[StructuredPatchHunk] = []

    for group in matcher.get_grouped_opcodes(3):
        hunk_lines: list[str] = []
        old_start = group[0][1] + 1
        old_end = group[-1][2]
        new_start = group[0][3] + 1
        new_end = group[-1][4]

        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for line in orig_lines[i1:i2]:
                    hunk_lines.append(" " + line.rstrip("\n"))
            elif tag == "delete":
                for line in orig_lines[i1:i2]:
                    hunk_lines.append("-" + line.rstrip("\n"))
            elif tag == "insert":
                for line in mod_lines[j1:j2]:
                    hunk_lines.append("+" + line.rstrip("\n"))
            elif tag == "replace":
                for line in orig_lines[i1:i2]:
                    hunk_lines.append("-" + line.rstrip("\n"))
                for line in mod_lines[j1:j2]:
                    hunk_lines.append("+" + line.rstrip("\n"))

        hunks.append(StructuredPatchHunk(
            old_start=old_start,
            old_lines=old_end - old_start + 1,
            new_start=new_start,
            new_lines=new_end - new_start + 1,
            lines=hunk_lines,
        ))

    return hunks


# ---------------------------------------------------------------------------
# Read file
# ---------------------------------------------------------------------------

@dataclass
class ReadFileOutput:
    file_path: str
    content: str
    num_lines: int
    start_line: int = 1
    total_lines: int = 0
    kind: str = "text"


def read_file(
    file_path: str,
    start_line: int | None = None,
    end_line: int | None = None,
    max_size: int = MAX_READ_SIZE,
) -> ReadFileOutput:
    """Read a file, optionally returning a line range.

    Lines are 1-indexed. Output includes cat -n style line numbers.
    Rejects binary files and files exceeding size limit.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if path.is_dir():
        raise IsADirectoryError(f"Path is a directory: {file_path}")

    # Size check
    file_size = path.stat().st_size
    if file_size > max_size:
        raise ValueError(
            f"File too large: {file_size:,} bytes (max: {max_size:,} bytes). "
            f"Use offset/limit to read portions."
        )

    # Binary check
    if is_binary_file(path):
        raise ValueError(f"Binary file detected: {file_path}. Cannot read binary files as text.")

    text = path.read_text(encoding="utf-8", errors="replace")
    all_lines = text.splitlines(keepends=True)
    total = len(all_lines)

    start = (start_line or 1) - 1  # Convert to 0-indexed
    end = end_line or total

    start = max(0, start)
    end = min(total, end)

    selected = all_lines[start:end]

    # Format with line numbers (cat -n style)
    numbered_lines = []
    for i, line in enumerate(selected, start=start + 1):
        numbered_lines.append(f"{i}\t{line}")

    content = "".join(numbered_lines)

    return ReadFileOutput(
        file_path=file_path,
        content=content,
        num_lines=len(selected),
        start_line=start + 1,
        total_lines=total,
    )


# ---------------------------------------------------------------------------
# Write file
# ---------------------------------------------------------------------------

@dataclass
class WriteFileOutput:
    file_path: str
    content: str
    kind: str = "create"
    structured_patch: list[StructuredPatchHunk] = field(default_factory=list)
    original_file: str | None = None


def write_file(
    file_path: str,
    content: str,
    max_size: int = MAX_WRITE_SIZE,
) -> WriteFileOutput:
    """Write content to a file, creating parent directories as needed.

    Validates content size and generates patch if updating existing file.
    """
    if len(content.encode("utf-8")) > max_size:
        raise ValueError(
            f"Content too large: {len(content.encode('utf-8')):,} bytes "
            f"(max: {max_size:,} bytes)"
        )

    path = Path(file_path)
    original = None
    kind = "create"

    if path.exists():
        kind = "update"
        original = path.read_text(encoding="utf-8", errors="replace")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")

    # Generate patch
    patch = []
    if original is not None:
        patch = make_patch(original, content, file_path)

    return WriteFileOutput(
        file_path=file_path,
        content=content,
        kind=kind,
        structured_patch=patch,
        original_file=original,
    )


# ---------------------------------------------------------------------------
# Edit file
# ---------------------------------------------------------------------------

@dataclass
class EditFileOutput:
    file_path: str
    old_string: str
    new_string: str
    replacements: int = 0
    structured_patch: list[StructuredPatchHunk] = field(default_factory=list)
    original_file: str = ""
    replace_all: bool = False


def edit_file(
    file_path: str,
    old_string: str,
    new_string: str,
    replace_all: bool = False,
) -> EditFileOutput:
    """Replace text in a file.

    If replace_all is False, old_string must be unique in the file.
    Validates old_string != new_string and generates patch.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    if old_string == new_string:
        raise ValueError("old_string and new_string are identical — no change needed")

    content = path.read_text(encoding="utf-8")
    count = content.count(old_string)

    if count == 0:
        raise ValueError(f"old_string not found in {file_path}")

    if not replace_all and count > 1:
        raise ValueError(
            f"old_string appears {count} times in {file_path}. "
            f"Use replace_all=True or provide more context to make it unique."
        )

    if replace_all:
        new_content = content.replace(old_string, new_string)
        replacements = count
    else:
        new_content = content.replace(old_string, new_string, 1)
        replacements = 1

    path.write_text(new_content, encoding="utf-8")

    # Generate patch
    patch = make_patch(content, new_content, file_path)

    return EditFileOutput(
        file_path=file_path,
        old_string=old_string,
        new_string=new_string,
        replacements=replacements,
        structured_patch=patch,
        original_file=content,
        replace_all=replace_all,
    )


# ---------------------------------------------------------------------------
# Glob search
# ---------------------------------------------------------------------------

@dataclass
class GlobSearchOutput:
    pattern: str
    filenames: list[str]
    num_files: int
    duration_ms: float
    truncated: bool = False


def glob_search(
    pattern: str,
    path: str | None = None,
    max_results: int = DEFAULT_GLOB_LIMIT,
) -> GlobSearchOutput:
    """Search for files matching a glob pattern.

    Results sorted by modification time (newest first). Truncates at max_results.
    """
    start = time.monotonic()
    search_root = Path(path) if path else Path.cwd()

    matches: list[str] = []
    truncated = False

    # Normalize pattern for rglob
    glob_pattern = pattern
    if glob_pattern.startswith("**/"):
        glob_pattern = glob_pattern[3:]

    try:
        for p in search_root.rglob(glob_pattern):
            if p.is_file():
                # Skip hidden dirs and common non-code dirs
                parts = p.relative_to(search_root).parts
                if any(
                    part.startswith(".") or part in (
                        "node_modules", "__pycache__", "target", "dist",
                        "build", "venv", ".venv",
                    )
                    for part in parts
                ):
                    continue

                matches.append(str(p))
                if len(matches) >= max_results:
                    truncated = True
                    break
    except (OSError, ValueError):
        pass

    duration_ms = (time.monotonic() - start) * 1000

    # Sort by modification time (most recent first)
    try:
        matches.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    except OSError:
        pass

    return GlobSearchOutput(
        pattern=pattern,
        filenames=matches,
        num_files=len(matches),
        duration_ms=duration_ms,
        truncated=truncated,
    )


# ---------------------------------------------------------------------------
# Grep search
# ---------------------------------------------------------------------------

@dataclass
class GrepMatch:
    file: str
    line_number: int
    content: str


@dataclass
class GrepSearchOutput:
    pattern: str
    matches: list[GrepMatch] = field(default_factory=list)
    filenames: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    truncated: bool = False
    num_matches: int = 0
    mode: str = "files_with_matches"
    content: str | None = None


def grep_search(
    pattern: str,
    path: str | None = None,
    glob_filter: str | None = None,
    output_mode: str = "files_with_matches",
    max_results: int = DEFAULT_HEAD_LIMIT,
    offset: int = 0,
    case_insensitive: bool = False,
    context_lines: int = 0,
    before_context: int = 0,
    after_context: int = 0,
    multiline: bool = False,
    file_type: str | None = None,
    line_numbers: bool = True,
) -> GrepSearchOutput:
    """Search file contents with regex pattern.

    Supports three output modes: files_with_matches, content, count.
    Filters by glob pattern and file type.
    """
    start = time.monotonic()
    search_root = Path(path) if path else Path.cwd()

    # Determine context
    ctx_before = before_context or context_lines
    ctx_after = after_context or context_lines

    flags = re.IGNORECASE if case_insensitive else 0
    if multiline:
        flags |= re.DOTALL | re.MULTILINE

    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise ValueError(f"Invalid regex pattern: {exc}") from exc

    # Build file type filter
    type_globs: list[str] = []
    if file_type:
        type_map = {
            "py": "*.py", "python": "*.py",
            "js": "*.js", "javascript": "*.js",
            "ts": "*.ts", "typescript": "*.ts",
            "tsx": "*.tsx",
            "rs": "*.rs", "rust": "*.rs",
            "go": "*.go",
            "java": "*.java",
            "c": "*.c", "cpp": "*.cpp", "cc": "*.cc",
            "h": "*.h", "hpp": "*.hpp",
            "rb": "*.rb", "ruby": "*.rb",
            "md": "*.md", "markdown": "*.md",
            "json": "*.json",
            "yaml": "*.yaml", "yml": "*.yml",
            "toml": "*.toml",
            "html": "*.html",
            "css": "*.css",
            "sql": "*.sql",
            "sh": "*.sh", "bash": "*.sh",
        }
        if file_type in type_map:
            type_globs = [type_map[file_type]]

    matches: list[GrepMatch] = []
    matched_files: set[str] = set()
    match_count = 0
    truncated = False
    content_lines: list[str] = []
    skipped = 0

    # Skip directories
    skip_dirs = {
        ".git", "node_modules", "__pycache__", "target", "dist",
        "build", "venv", ".venv", "env", ".tox", ".mypy_cache",
    }

    for root, dirs, files in os.walk(search_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs and not d.startswith(".")]

        for filename in files:
            # Filter by glob/type
            if glob_filter and not fnmatch.fnmatch(filename, glob_filter):
                continue
            if type_globs and not any(fnmatch.fnmatch(filename, g) for g in type_globs):
                continue

            filepath = os.path.join(root, filename)

            try:
                with open(filepath, encoding="utf-8", errors="ignore") as f:
                    file_lines = f.readlines()
            except (OSError, PermissionError):
                continue

            file_matched = False
            for line_num, line in enumerate(file_lines, 1):
                if compiled.search(line):
                    file_matched = True
                    match_count += 1

                    # Apply offset
                    if skipped < offset:
                        skipped += 1
                        continue

                    if output_mode == "content":
                        # Add context lines
                        if ctx_before > 0:
                            start_ctx = max(0, line_num - 1 - ctx_before)
                            for ctx_i in range(start_ctx, line_num - 1):
                                ctx_line = file_lines[ctx_i].rstrip("\n")
                                prefix = f"{filepath}:{ctx_i + 1}:" if line_numbers else ""
                                content_lines.append(f"{prefix}{ctx_line}")

                        prefix = f"{filepath}:{line_num}:" if line_numbers else ""
                        content_lines.append(f"{prefix}{line.rstrip(chr(10))}")

                        if ctx_after > 0:
                            end_ctx = min(len(file_lines), line_num + ctx_after)
                            for ctx_i in range(line_num, end_ctx):
                                ctx_line = file_lines[ctx_i].rstrip("\n")
                                prefix = f"{filepath}:{ctx_i + 1}:" if line_numbers else ""
                                content_lines.append(f"{prefix}{ctx_line}")

                    matches.append(GrepMatch(
                        file=filepath,
                        line_number=line_num,
                        content=line.rstrip("\n"),
                    ))

                    if len(matches) >= max_results:
                        truncated = True
                        break

            if file_matched:
                matched_files.add(filepath)

            if truncated:
                break
        if truncated:
            break

    duration_ms = (time.monotonic() - start) * 1000

    result = GrepSearchOutput(
        pattern=pattern,
        matches=matches,
        filenames=sorted(matched_files),
        duration_ms=duration_ms,
        truncated=truncated,
        num_matches=match_count,
        mode=output_mode,
    )

    if output_mode == "content" and content_lines:
        result.content = "\n".join(content_lines[:max_results])

    return result
