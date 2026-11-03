"""Bash command execution with timeout, sandbox, and background support.

Maps to: rust/crates/runtime/src/bash.rs
"""

from __future__ import annotations

import asyncio
import enum
import logging
import os
import sys
import time
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

@dataclass
class _BackgroundTask:
    process: asyncio.subprocess.Process
    command: str
    started_at: float
    chunks: list[str] = field(default_factory=list)
    read_offset: int = 0  # chars already handed to a reader (so reads return only new output)
    exit_code: int | None = None
    drain_task: Any = None


_background_tasks: dict[str, _BackgroundTask] = {}


def get_background_task(task_id: str) -> asyncio.subprocess.Process | None:
    """Get a background task's process by ID (legacy accessor)."""
    bt = _background_tasks.get(task_id)
    return bt.process if bt else None


async def _drain_background(bt: "_BackgroundTask") -> None:
    """Continuously read the process's stdout/stderr into its buffer until it exits."""
    async def pump(stream: Any, prefix: str = "") -> None:
        if stream is None:
            return
        while True:
            line = await stream.readline()
            if not line:
                break
            bt.chunks.append(prefix + line.decode("utf-8", errors="replace"))
    try:
        await asyncio.gather(
            pump(bt.process.stdout),
            pump(bt.process.stderr, "[stderr] "),
            return_exceptions=True,
        )
        bt.exit_code = await bt.process.wait()
    except Exception:  # pragma: no cover - defensive
        bt.exit_code = bt.exit_code if bt.exit_code is not None else -1


def read_background_output(task_id: str, kill: bool = False) -> dict[str, Any] | None:
    """Return new output + status for a background task (None if unknown).

    Returns only output not yet read (tracked per task), so repeated polls show just what's new.
    """
    bt = _background_tasks.get(task_id)
    if bt is None:
        return None
    if kill and bt.exit_code is None:
        try:
            bt.process.kill()
        except ProcessLookupError:
            pass
    full = "".join(bt.chunks)
    new_output = full[bt.read_offset:]
    bt.read_offset = len(full)
    return {
        "task_id": task_id,
        "command": bt.command,
        "running": bt.exit_code is None,
        "exit_code": bt.exit_code,
        "new_output": new_output,
        "elapsed_s": round(time.time() - bt.started_at, 1),
    }


def list_background_tasks() -> list[dict[str, Any]]:
    return [
        {
            "task_id": tid,
            "command": bt.command,
            "running": bt.exit_code is None,
            "exit_code": bt.exit_code,
            "elapsed_s": round(time.time() - bt.started_at, 1),
        }
        for tid, bt in _background_tasks.items()
    ]


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
# Process helpers
# ---------------------------------------------------------------------------

def _kill_process(process: asyncio.subprocess.Process) -> None:
    """Kill a subprocess safely."""
    try:
        process.kill()
    except (ProcessLookupError, OSError):
        pass


async def _stream_process(
    process: asyncio.subprocess.Process,
    description: str = "",
) -> tuple[bytes, str]:
    """Read stdout fully while showing a live updating status line on stderr.

    Shows a single line that keeps updating with the latest stderr output,
    like Claude Code's "Running...", "Installing packages...", etc.

    Returns (stdout_bytes, stderr_text).
    """
    assert process.stdout is not None
    assert process.stderr is not None

    stderr_lines: list[str] = []
    _spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    _frame_idx = [0]

    def _clean_status(line: str) -> str:
        """Extract a clean status message from a stderr line."""
        line = line.strip()
        if not line:
            return ""
        # Skip noisy lines (progress bars, ANSI escapes, blank/repeated)
        if line.startswith(("\x1b", "\033")) or set(line) <= set("-=>#. "):
            return ""
        # Truncate to fit one line
        return line[:80]

    async def _read_stderr() -> None:
        """Read stderr line-by-line and update the status line."""
        assert process.stderr is not None
        while True:
            line_bytes = await process.stderr.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\n\r")
            stderr_lines.append(line)

            status = _clean_status(line)
            if status:
                frame = _spinner_frames[_frame_idx[0] % len(_spinner_frames)]
                _frame_idx[0] += 1
                # Overwrite the same line — \r returns to start, \033[K clears to end
                sys.stderr.write(f"\r\033[K  {frame} {status}")
                sys.stderr.flush()

    async def _read_stdout() -> bytes:
        """Also show status updates from stdout for commands that log there."""
        assert process.stdout is not None
        chunks: list[bytes] = []
        while True:
            chunk = await process.stdout.read(4096)
            if not chunk:
                break
            chunks.append(chunk)
            # Extract last line for status
            text = chunk.decode("utf-8", errors="replace")
            last_line = text.rstrip().rsplit("\n", 1)[-1]
            status = _clean_status(last_line)
            if status:
                frame = _spinner_frames[_frame_idx[0] % len(_spinner_frames)]
                _frame_idx[0] += 1
                sys.stderr.write(f"\r\033[K  {frame} {status}")
                sys.stderr.flush()
        return b"".join(chunks)

    # Show initial status
    label = description or "Running"
    sys.stderr.write(f"\r\033[K  {_spinner_frames[0]} {label}...")
    sys.stderr.flush()

    # Run stderr reader concurrently with stdout collection
    stderr_task = asyncio.create_task(_read_stderr())
    stdout_bytes = await _read_stdout()
    await stderr_task
    await process.wait()

    # Clear the status line
    sys.stderr.write("\r\033[K")
    sys.stderr.flush()

    return stdout_bytes, "\n".join(stderr_lines)


# ---------------------------------------------------------------------------
# Main execution
# ---------------------------------------------------------------------------

async def execute_bash(input_cfg: BashCommandInput) -> BashCommandOutput:
    """Execute a bash command asynchronously.

    Streams stderr to the terminal in real-time so the user can see progress
    from long-running commands (builds, installs, copies).  Ctrl+C during
    execution kills only this command, not the whole session.

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
            # Stream stderr in real-time while collecting stdout
            stdout_bytes, stderr_text = await asyncio.wait_for(
                _stream_process(process, description=input_cfg.description),
                timeout=timeout_secs,
            )
        except asyncio.CancelledError:
            # Ctrl+C hit — kill just this command
            _kill_process(process)
            return BashCommandOutput(
                stdout="",
                stderr="Command cancelled by user (Ctrl+C)",
                exit_code=None,
                interrupted=True,
            )
        except asyncio.TimeoutError:
            _kill_process(process)
            return BashCommandOutput(
                stdout="",
                stderr=f"Command exceeded timeout of {input_cfg.timeout_ms}ms",
                exit_code=None,
                timed_out=True,
                interrupted=True,
            )

        stdout = truncate_output(stdout_bytes.decode("utf-8", errors="replace"))
        stderr = truncate_output(stderr_text)

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
        # Capture output (was DEVNULL, which threw it away) so it can be read back via read_background_output.
        process = await asyncio.create_subprocess_exec(
            *shell_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            limit=4 * 1024 * 1024,
        )

        task_id = f"bg-{uuid.uuid4().hex[:8]}"
        bt = _BackgroundTask(process=process, command=input_cfg.command, started_at=time.time())
        bt.drain_task = asyncio.ensure_future(_drain_background(bt))
        _background_tasks[task_id] = bt

        return BashCommandOutput(
            background_task_id=task_id,
            stdout=(
                f"Background task started: {task_id} (PID: {process.pid}). "
                f"Use BashOutput with task_id={task_id} to read its output or kill it."
            ),
        )
    except Exception as exc:
        return BashCommandOutput(
            stderr=f"Failed to start background task: {exc}",
            exit_code=1,
        )
