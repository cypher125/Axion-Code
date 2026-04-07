"""Hook system for pre/post tool execution.

Maps to: rust/crates/runtime/src/hooks.rs
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class HookEvent(enum.Enum):
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"


@dataclass
class HookRunResult:
    """Result of running hooks for a single event."""

    denied: bool = False
    failed: bool = False
    cancelled: bool = False
    messages: list[str] = field(default_factory=list)
    permission_override: str | None = None
    permission_reason: str | None = None
    updated_input: str | None = None


@dataclass
class HookConfig:
    """Configuration for a single hook."""

    command: str
    timeout_ms: int = 10_000


@runtime_checkable
class HookProgressReporter(Protocol):
    """Protocol for hook progress reporting."""

    def on_hook_started(self, event: HookEvent, tool_name: str, command: str) -> None: ...
    def on_hook_completed(self, event: HookEvent, tool_name: str, command: str) -> None: ...


class HookRunner:
    """Executes hooks as subprocesses.

    Maps to: rust/crates/runtime/src/hooks.rs::HookRunner
    """

    def __init__(
        self,
        pre_tool_use: list[HookConfig] | None = None,
        post_tool_use: list[HookConfig] | None = None,
        post_tool_use_failure: list[HookConfig] | None = None,
        progress_reporter: HookProgressReporter | None = None,
    ) -> None:
        self.pre_tool_use = pre_tool_use or []
        self.post_tool_use = post_tool_use or []
        self.post_tool_use_failure = post_tool_use_failure or []
        self.progress_reporter = progress_reporter

    @classmethod
    def from_config(cls, hooks_data: dict[str, Any]) -> HookRunner:
        """Create HookRunner from configuration dict."""
        def parse_hooks(data: list[Any]) -> list[HookConfig]:
            configs = []
            for item in data:
                if isinstance(item, str):
                    configs.append(HookConfig(command=item))
                elif isinstance(item, dict):
                    configs.append(HookConfig(
                        command=item.get("command", ""),
                        timeout_ms=item.get("timeout_ms", 10_000),
                    ))
            return configs

        return cls(
            pre_tool_use=parse_hooks(hooks_data.get("preToolUse", [])),
            post_tool_use=parse_hooks(hooks_data.get("postToolUse", [])),
            post_tool_use_failure=parse_hooks(hooks_data.get("postToolUseFailure", [])),
        )

    async def run_pre_tool_use(
        self, tool_name: str, tool_input: str
    ) -> HookRunResult:
        """Run pre-tool-use hooks. Returns deny if any hook exits with code 2."""
        return await self._run_hooks(
            HookEvent.PRE_TOOL_USE,
            self.pre_tool_use,
            tool_name,
            tool_input,
        )

    async def run_post_tool_use(
        self, tool_name: str, tool_input: str, tool_output: str, is_error: bool
    ) -> HookRunResult:
        """Run post-tool-use hooks."""
        return await self._run_hooks(
            HookEvent.POST_TOOL_USE,
            self.post_tool_use,
            tool_name,
            tool_input,
            tool_output=tool_output,
            is_error=is_error,
        )

    async def run_post_tool_use_failure(
        self, tool_name: str, tool_input: str, error: str
    ) -> HookRunResult:
        """Run post-tool-use-failure hooks."""
        return await self._run_hooks(
            HookEvent.POST_TOOL_USE_FAILURE,
            self.post_tool_use_failure,
            tool_name,
            tool_input,
            tool_output=error,
            is_error=True,
        )

    async def _run_hooks(
        self,
        event: HookEvent,
        hooks: list[HookConfig],
        tool_name: str,
        tool_input: str,
        tool_output: str = "",
        is_error: bool = False,
    ) -> HookRunResult:
        """Run a list of hooks sequentially."""
        result = HookRunResult()

        for hook in hooks:
            if self.progress_reporter:
                self.progress_reporter.on_hook_started(event, tool_name, hook.command)

            try:
                hook_result = await self._execute_hook(
                    hook, event, tool_name, tool_input, tool_output, is_error
                )
            except Exception as exc:
                logger.error("Hook '%s' failed: %s", hook.command, exc)
                result.failed = True
                result.messages.append(f"Hook error: {exc}")
                continue

            if self.progress_reporter:
                self.progress_reporter.on_hook_completed(event, tool_name, hook.command)

            if hook_result.denied:
                return hook_result
            if hook_result.messages:
                result.messages.extend(hook_result.messages)
            if hook_result.updated_input:
                result.updated_input = hook_result.updated_input

        return result

    async def _execute_hook(
        self,
        hook: HookConfig,
        event: HookEvent,
        tool_name: str,
        tool_input: str,
        tool_output: str,
        is_error: bool,
    ) -> HookRunResult:
        """Execute a single hook as a subprocess."""
        # Build environment
        env = {
            **os.environ,
            "HOOK_EVENT": event.value,
            "HOOK_TOOL_NAME": tool_name,
            "HOOK_TOOL_INPUT": tool_input,
            "HOOK_TOOL_OUTPUT": tool_output,
            "HOOK_TOOL_IS_ERROR": str(is_error).lower(),
        }

        # Build payload
        payload = json.dumps({
            "event": event.value,
            "tool_name": tool_name,
            "tool_input": tool_input,
            "tool_output": tool_output,
            "is_error": is_error,
        })

        timeout_secs = hook.timeout_ms / 1000.0

        process = await asyncio.create_subprocess_shell(
            hook.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(input=payload.encode()),
                timeout=timeout_secs,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return HookRunResult(failed=True, messages=["Hook timed out"])

        exit_code = process.returncode
        result = HookRunResult()

        if stdout:
            result.messages.append(stdout.decode("utf-8", errors="replace").strip())

        # Exit code 0 = allow, 2 = deny, anything else = error
        if exit_code == 0:
            pass
        elif exit_code == 2:
            result.denied = True
            reason = stderr.decode("utf-8", errors="replace").strip() if stderr else "Hook denied"
            result.messages.append(reason)
        else:
            result.failed = True
            if stderr:
                result.messages.append(stderr.decode("utf-8", errors="replace").strip())

        return result
