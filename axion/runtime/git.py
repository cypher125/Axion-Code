"""Git workflow operations.

Maps to: rust/crates/runtime/src/git.rs

Provides typed wrappers around common git commands using subprocess.run
with proper error handling.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Error from a git operation."""

    def __init__(self, message: str, *, returncode: int = 1) -> None:
        super().__init__(message)
        self.returncode = returncode


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class GitStatus:
    """Parsed output of ``git status``."""

    branch: str
    clean: bool
    staged: int = 0
    modified: int = 0
    untracked: int = 0


@dataclass
class GitCommit:
    """A single commit from ``git log``."""

    hash: str
    author: str
    date: str
    message: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(
    args: list[str],
    cwd: Path,
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command with standard options."""
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"Git command timed out: {' '.join(args)}") from exc
    except FileNotFoundError as exc:
        raise GitError("git executable not found") from exc

    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise GitError(
            f"git {args[1] if len(args) > 1 else ''} failed: {stderr}",
            returncode=result.returncode,
        )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def git_status(cwd: Path) -> GitStatus:
    """Return parsed status (branch, clean/dirty, file counts)."""
    # Branch name
    branch_result = _run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd, check=False
    )
    branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

    # Porcelain status for counts
    result = _run(["git", "status", "--porcelain"], cwd)
    lines = [line for line in result.stdout.splitlines() if line.strip()]

    staged = 0
    modified = 0
    untracked = 0

    for line in lines:
        if len(line) < 2:
            continue
        x, y = line[0], line[1]
        if x == "?":
            untracked += 1
        else:
            if x in "ACDMR":
                staged += 1
            if y in "ACDMR":
                modified += 1

    return GitStatus(
        branch=branch,
        clean=len(lines) == 0,
        staged=staged,
        modified=modified,
        untracked=untracked,
    )


def git_log(cwd: Path, n: int = 10) -> list[GitCommit]:
    """Return recent commits."""
    result = _run(
        [
            "git",
            "log",
            f"-{n}",
            "--format=%H%n%an%n%ai%n%s%n---",
        ],
        cwd,
    )

    commits: list[GitCommit] = []
    entries = result.stdout.strip().split("---\n")
    for entry in entries:
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("\n", 3)
        if len(parts) >= 4:
            commits.append(
                GitCommit(
                    hash=parts[0].strip(),
                    author=parts[1].strip(),
                    date=parts[2].strip(),
                    message=parts[3].strip(),
                )
            )
        elif len(parts) == 3:
            commits.append(
                GitCommit(
                    hash=parts[0].strip(),
                    author=parts[1].strip(),
                    date=parts[2].strip(),
                    message="",
                )
            )

    return commits


def git_diff(cwd: Path, staged: bool = False) -> str:
    """Return diff output."""
    args = ["git", "diff"]
    if staged:
        args.append("--staged")
    result = _run(args, cwd)
    return result.stdout


def git_branch(cwd: Path) -> str:
    """Return current branch name."""
    result = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd)
    return result.stdout.strip()


def git_commit(cwd: Path, message: str, files: list[str]) -> str:
    """Stage specific files and commit."""
    if not files:
        raise GitError("No files specified for commit")

    # Stage files
    _run(["git", "add", "--"] + files, cwd)

    # Commit
    result = _run(["git", "commit", "-m", message], cwd)
    return result.stdout.strip()


def git_create_branch(cwd: Path, name: str) -> str:
    """Create and checkout a new branch."""
    result = _run(["git", "checkout", "-b", name], cwd)
    return result.stdout.strip() or result.stderr.strip()


def git_stash(cwd: Path) -> str:
    """Stash current changes."""
    result = _run(["git", "stash"], cwd)
    return result.stdout.strip()


def git_stash_pop(cwd: Path) -> str:
    """Pop the most recent stash."""
    result = _run(["git", "stash", "pop"], cwd)
    return result.stdout.strip()
