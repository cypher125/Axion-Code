"""Tests for bash execution."""

import pytest

from axion.runtime.bash import (
    MAX_OUTPUT_BYTES,
    BashCommandInput,
    execute_bash,
    truncate_output,
)


@pytest.mark.asyncio
async def test_execute_echo():
    result = await execute_bash(BashCommandInput(command="echo hello"))
    assert "hello" in result.stdout
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_execute_exit_code():
    result = await execute_bash(BashCommandInput(command="exit 42"))
    assert result.exit_code == 42


@pytest.mark.asyncio
async def test_execute_timeout():
    # Use a very short timeout
    result = await execute_bash(BashCommandInput(
        command="ping -n 10 127.0.0.1" if __import__("sys").platform == "win32" else "sleep 10",
        timeout_ms=500,
    ))
    assert result.timed_out


@pytest.mark.asyncio
async def test_execute_stderr():
    result = await execute_bash(BashCommandInput(command="echo error 1>&2"))
    assert "error" in result.stderr


def test_truncate_output():
    short = "hello"
    assert truncate_output(short) == short

    long = "x" * (MAX_OUTPUT_BYTES + 1000)
    truncated = truncate_output(long)
    assert len(truncated.encode("utf-8")) <= MAX_OUTPUT_BYTES + 100  # +100 for notice
    assert "truncated" in truncated


@pytest.mark.asyncio
async def test_execute_background():
    result = await execute_bash(BashCommandInput(
        command="echo bg",
        run_in_background=True,
    ))
    assert result.background_task_id is not None
