"""Tests for hook system."""

import pytest

from claw.runtime.hooks import HookConfig, HookRunner


@pytest.mark.asyncio
async def test_hook_runner_no_hooks():
    runner = HookRunner()
    result = await runner.run_pre_tool_use("Bash", '{"command": "ls"}')
    assert not result.denied
    assert not result.failed


@pytest.mark.asyncio
async def test_hook_runner_from_config():
    runner = HookRunner.from_config({
        "preToolUse": ["echo ok"],
        "postToolUse": [],
    })
    assert len(runner.pre_tool_use) == 1
    assert runner.pre_tool_use[0].command == "echo ok"
