"""Bash command execution with timeout, sandbox, and background support.

Maps to: rust/crates/runtime/src/bash.rs
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_MS = 120_000  # 2 minutes
MAX_TIMEOUT_MS = 600_000  # 10 minutes
MAX_OUTPUT_BYTES = 16_384  # 16 KiB (matching Rust)
TRUNCATION_NOTICE = "\n\n[output truncated — exceeded 16384 bytes]"


class FilesystemIsolationMode(enum.Enum):
    NONE = "none"
    WORKSPACE_ONLY = "workspace_only"
    READ_ONLY = "read_only"


class SandboxStatus(enum.Enum):
    DISABLED = "disabled"
    ENABLED = "enabled"
    UNAVAILABLE = "unavailable"


@dataclass
class BashCommandInput:
    """Input for a bash command execution."""

    command: str
    timeout_ms: int = DEFAULT_TIMEOUT_MS
    description: str = ""
    run_in_background: bool = False
    cwd: Path | None = None
    dangerously_disable_sandbox: bool = False
    namespace_restrictions: bool | None = None
    isolate_network: bool | None = None
    filesystem_mode: FilesystemIsolationMode | None = None
    allowed_mounts: list[str] | None = None


@dataclass
class BashCommandOutput:
    """Output from a bash command execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    interrupted: bool = False
    timed_out: bool = False
    background_task_id: str | None = None
    is_image: bool = False
    no_output_expected: bool = False
    sandbox_status: SandboxStatus | None = None
    return_code_interpretation: str | None = None
    raw_output_path: str | None = None


# ---------------------------------------------------------------------------
# Background task tracking
# ---------------------------------------------------------------------------

_background_tasks: dict[str, asyncio.subprocess.Process] = {}


def get_background_task(task_id: str) -> asyncio.subprocess.Process | None:
    """Get a background task by ID."""
    return _background_tasks.get(task_id)


# ---------------------------------------------------------------------------
# Output truncation (matching Rust)
# ---------------------------------------------------------------------------

def truncate_output(text: str, max_bytes: int = MAX_OUTPUT_BYTES) -> str:
    """Truncate output to max_bytes, respecting UTF-8 boundaries."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    # Find last valid UTF-8 boundary
    truncated = encoded[:max_bytes]
    result = truncated.decode("utf-8", errors="ignore")
    return result + TRUNCATION_NOTICE


# ---------------------------------------------------------------------------
# Sandbox support
# ---------------------------------------------------------------------------

def _build_sandbox_command(
    command: str,
    cwd: Path | None,
    input_cfg: BashCommandInput,
) -> list[str]:
    """Build the shell command, potentially wrapped in sandbox."""
    # Check for Linux sandbox tools
    if sys.platform == "linux" and not input_cfg.dangerously_disable_sandbox:
        bwrap = Path("/usr/bin/bwrap")
        if bwrap.exists() and input_cfg.filesystem_mode:
            # Build bubblewrap command
            args = [
                str(bwrap),
                "--unshare-all",
                "--die-with-parent",
            ]
            # Add filesystem mounts
            if input_cfg.filesystem_mode == FilesystemIsolationMode.WORKSPACE_ONLY:
                workspace = str(cwd) if cwd else os.getcwd()
                args.extend(["--bind", workspace, workspace])
                args.extend(["--ro-bind", "/usr", "/usr"])
                args.extend(["--ro-bind", "/bin", "/bin"])
                args.extend(["--ro-bind", "/lib", "/lib"])
                if Path("/lib64").exists():
                    args.extend(["--ro-bind", "/lib64", "/lib64"])
                args.extend(["--proc", "/proc"])
                args.extend(["--dev", "/dev"])
                args.extend(["--tmpfs", "/tmp"])
            elif input_cfg.filesystem_mode == FilesystemIsolationMode.READ_ONLY:
                args.extend(["--ro-bind", "/", "/"])

            # Network isolation
            if input_cfg.isolate_network:
                args.extend(["--unshare-net"])

            # Additional mounts
            if input_cfg.allowed_mounts:
                for mount in input_cfg.allowed_mounts:
                    args.extend(["--bind", mount, mount])

            args.extend(["--", "sh", "-c", command])
            return args

    # Default: use available shell
    if sys.platform == "win32":
        # On Windows, try Git Bash first, then fall back to cmd
        git_bash = Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if git_bash.exists():
            return [str(git_bash), "-c", command]
        # Fallback to cmd.exe
        return ["cmd", "/C", command]
    return ["/bin/bash", "-lc", command]


# ---------------------------------------------------------------------------
# Sandbox home directory setup
# ---------------------------------------------------------------------------

def _prepare_sandbox_dirs(cwd: Path | None) -> dict[str, str]:
    """Create sandbox home/tmp directories and return env overrides."""
    workspace = cwd or Path.cwd()
    sandbox_home = workspace / ".sandbox-home"
    sandbox_tmp = workspace / ".sandbox-tmp"
    sandbox_home.mkdir(exist_ok=True)
    sandbox_tmp.mkdir(exist_ok=True)
    return {
        "HOME": str(sandbox_home),
        "TMPDIR": str(sandbox_tmp),
    }


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

async def execute_bash(input_cfg: BashCommandInput) -> BashCommandOutput:
    """Execute a bash command asynchronously.

    Maps to: rust/crates/runtime/src/bash.rs::execute_bash
    """
    timeout_secs = min(input_cfg.timeout_ms, MAX_TIMEOUT_MS) / 1000.0
    cwd = str(input_cfg.cwd) if input_cfg.cwd else None

    # Background execution
    if input_cfg.run_in_background:
        return await _execute_background(input_cfg, cwd)

    # Build command
    shell_cmd = _build_sandbox_command(input_cfg.command, input_cfg.cwd, input_cfg)

    # Build environment
    env = dict(os.environ)
    if input_cfg.filesystem_mode and input_cfg.filesystem_mode != FilesystemIsolationMode.NONE:
        sandbox_env = _prepare_sandbox_dirs(input_cfg.cwd)
        env.update(sandbox_env)

    try:
        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=env,
        )

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                process.communicate(), timeout=timeout_secs
            )
        except asyncio.TimeoutError:
            try:
                process.kill()
                await process.wait()
            except ProcessLookupError:
                pass
            return BashCommandOutput(
                stdout="",
                stderr=f"Command exceeded timeout of {input_cfg.timeout_ms}ms",
                exit_code=None,
                timed_out=True,
                interrupted=True,
            )

        stdout = truncate_output(stdout_bytes.decode("utf-8", errors="replace"))
        stderr = truncate_output(stderr_bytes.decode("utf-8", errors="replace"))

        exit_code = process.returncode
        return_code_interp = None
        if exit_code is not None and exit_code != 0:
            return_code_interp = f"exit_code:{exit_code}"

        return BashCommandOutput(
            stdout=stdout,
            stderr=stderr,
            exit_code=exit_code,
            no_output_expected=(not stdout.strip() and not stderr.strip()),
            return_code_interpretation=return_code_interp,
        )

    except FileNotFoundError:
        return BashCommandOutput(
            stdout="",
            stderr="bash: command not found. Is bash installed?",
            exit_code=127,
        )
    except Exception as exc:
        logger.error("Failed to execute bash command: %s", exc)
        return BashCommandOutput(
            stdout="",
            stderr=f"Execution error: {exc}",
            exit_code=1,
        )


async def _execute_background(
    input_cfg: BashCommandInput, cwd: str | None
) -> BashCommandOutput:
    """Execute a command in the background, returning immediately."""
    shell_cmd = _build_sandbox_command(input_cfg.command, input_cfg.cwd, input_cfg)

    try:
        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            cwd=cwd,
        )

        task_id = f"bg-{uuid.uuid4().hex[:8]}"
        _background_tasks[task_id] = process

        return BashCommandOutput(
            background_task_id=task_id,
            stdout=f"Background task started: {task_id} (PID: {process.pid})",
        )
    except Exception as exc:
        return BashCommandOutput(
            stderr=f"Failed to start background task: {exc}",
            exit_code=1,
        )
