"""Core conversation loop - coordinates model, tools, hooks, and session.

Maps to: rust/crates/runtime/src/conversation.rs

The ConversationRuntime orchestrates the full model turn loop including:
- Streaming model responses and assembling tool-use blocks
- Pre/post tool-use hook integration with permission override support
- Auto-compaction when cumulative input tokens exceed a threshold
- Session tracing for observability (turn lifecycle, tool execution)
- Prompt cache event collection from stream metadata
- Builder pattern for ergonomic construction
- Session forking for parallel exploration branches
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

from axion.api.client import (
    ProviderClient,
    max_tokens_for_model,
    resolve_model_alias,
)
from axion.api.types import (
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    InputJsonDelta,
    InputMessage,
    MessageDeltaEvent,
    MessageRequest,
    MessageStartEvent,
    MessageStopEvent,
    TextDelta,
    ToolUseOutputBlock,
)
from axion.runtime.compact import (
    CompactionConfig,
    CompactionResult,
    compact_session,
    estimate_session_tokens,
)
from axion.runtime.hooks import HookRunner
from axion.runtime.permissions import (
    PermissionAllow,
    PermissionDeny,
    PermissionOutcome,
    PermissionOverride,
    PermissionPolicy,
    PermissionPrompter,
)
from axion.runtime.session import (
    ContentBlock,
    ConversationMessage,
    MessageRole,
    Session,
    SessionFork,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from axion.runtime.usage import TokenUsage, UsageTracker
from axion.telemetry.tracer import SessionTracer

logger = logging.getLogger(__name__)

DEFAULT_AUTO_COMPACTION_THRESHOLD = 100_000
_ENV_COMPACTION_KEY = "CLAUDE_CODE_AUTO_COMPACT_INPUT_TOKENS"

# Context window sizes per model family (in tokens)
_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-opus": 200_000,
    "claude-sonnet": 200_000,
    "claude-haiku": 200_000,
}


# ---------------------------------------------------------------------------
# Protocols (traits)
# ---------------------------------------------------------------------------

@runtime_checkable
class ToolExecutor(Protocol):
    """Trait for tool dispatchers that execute model-requested tools."""

    async def execute(self, tool_name: str, tool_input: str) -> str: ...


# ---------------------------------------------------------------------------
# Events emitted during a turn
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AssistantTextDelta:
    """Incremental text chunk from the model."""
    text: str


@dataclass(frozen=True)
class AssistantToolUse:
    """Model requested a tool invocation."""
    id: str
    name: str
    input: str


@dataclass(frozen=True)
class AssistantUsage:
    """Token usage snapshot for a single iteration."""
    usage: TokenUsage


@dataclass(frozen=True)
class AssistantPromptCache:
    """Prompt cache hit/miss information from streaming metadata."""
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


@dataclass(frozen=True)
class AssistantMessageStop:
    """End of model message, includes stop reason."""
    stop_reason: str | None


AssistantEvent = (
    AssistantTextDelta
    | AssistantToolUse
    | AssistantUsage
    | AssistantPromptCache
    | AssistantMessageStop
)


# ---------------------------------------------------------------------------
# Prompt cache event tracking
# ---------------------------------------------------------------------------

@dataclass
class PromptCacheEvent:
    """Collected prompt cache stats from a single streaming response."""
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    timestamp_ms: int = 0


# ---------------------------------------------------------------------------
# Turn summary
# ---------------------------------------------------------------------------

@dataclass
class TurnSummary:
    """Summary of one completed runtime turn."""

    assistant_messages: list[ConversationMessage] = field(default_factory=list)
    tool_results: list[ConversationMessage] = field(default_factory=list)
    iterations: int = 0
    usage: TokenUsage = field(default_factory=TokenUsage)
    text_output: str = ""
    prompt_cache_events: list[PromptCacheEvent] = field(default_factory=list)
    compaction_result: CompactionResult | None = None
    was_auto_compacted: bool = False


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ConversationError(Exception):
    """Error during conversation turn."""

    def __init__(self, message: str, *, cause: Exception | None = None) -> None:
        super().__init__(message)
        self.cause = cause


class ToolError(Exception):
    """Error from tool execution."""

    def __init__(
        self,
        message: str,
        *,
        tool_name: str = "",
        tool_use_id: str = "",
        cause: Exception | None = None,
    ) -> None:
        super().__init__(message)
        self.tool_name = tool_name
        self.tool_use_id = tool_use_id
        self.cause = cause


class MaxIterationsError(ConversationError):
    """Raised when the tool loop exceeds max_iterations."""


class PermissionDeniedError(ConversationError):
    """Raised when a tool is denied by permission policy or hooks."""


class ContextWindowExceededError(ConversationError):
    """Raised when estimated tokens exceed the model's context window."""


# ---------------------------------------------------------------------------
# Conversation runtime
# ---------------------------------------------------------------------------

@dataclass
class ConversationRuntime:
    """Coordinates the model loop, tool execution, and session updates.

    Maps to: rust/crates/runtime/src/conversation.rs::ConversationRuntime

    The runtime implements the full agentic loop:
      1. Send user message + history to model
      2. Stream and assemble the response (text + tool_use blocks)
      3. For each tool_use: run pre-hooks, check permissions, execute, run post-hooks
      4. Append results, check auto-compaction, and loop
      5. Return when model produces final text (end_turn) or max iterations reached
    """

    session: Session
    provider: ProviderClient
    tool_executor: ToolExecutor | None = None
    permission_policy: PermissionPolicy = field(default_factory=PermissionPolicy)
    permission_prompter: PermissionPrompter | None = None
    hook_runner: HookRunner | None = None
    session_tracer: SessionTracer | None = None
    system_prompt: str = ""
    model: str = "claude-sonnet-4-6"
    max_iterations: int = 50
    auto_compaction_threshold: int = field(default_factory=lambda: _resolve_compaction_threshold())
    usage_tracker: UsageTracker = field(default_factory=UsageTracker)
    on_event: Callable[[AssistantEvent], None] | None = None
    on_text_delta: Callable[[str], None] | None = None  # Legacy callback

    # -- Builder helpers -----------------------------------------------------

    def with_max_iterations(self, n: int) -> ConversationRuntime:
        """Set maximum tool-loop iterations per turn."""
        self.max_iterations = n
        return self

    def with_auto_compaction_threshold(self, tokens: int) -> ConversationRuntime:
        """Set the input-token threshold that triggers auto-compaction."""
        self.auto_compaction_threshold = tokens
        return self

    def with_hook_runner(self, runner: HookRunner) -> ConversationRuntime:
        """Attach a hook runner for pre/post tool-use hooks."""
        self.hook_runner = runner
        return self

    def with_session_tracer(self, tracer: SessionTracer) -> ConversationRuntime:
        """Attach a session tracer for observability."""
        self.session_tracer = tracer
        return self

    def with_permission_prompter(self, prompter: PermissionPrompter) -> ConversationRuntime:
        """Attach an interactive permission prompter for PROMPT mode."""
        self.permission_prompter = prompter
        return self

    def with_tool_executor(self, executor: ToolExecutor) -> ConversationRuntime:
        """Set the tool executor."""
        self.tool_executor = executor
        return self

    def with_system_prompt(self, prompt: str) -> ConversationRuntime:
        """Set the system prompt."""
        self.system_prompt = prompt
        return self

    # -- Session operations --------------------------------------------------

    def fork_session(self, branch_name: str | None = None) -> ConversationRuntime:
        """Create a forked copy of this runtime with a new session.

        The forked session shares the conversation history up to this point
        but diverges from here. The fork metadata references the parent.
        """
        import copy

        forked_session = Session(
            messages=copy.deepcopy(self.session.messages),
            compaction=copy.deepcopy(self.session.compaction),
            fork=SessionFork(
                parent_session_id=self.session.session_id,
                branch_name=branch_name,
            ),
        )

        return ConversationRuntime(
            session=forked_session,
            provider=self.provider,
            tool_executor=self.tool_executor,
            permission_policy=self.permission_policy,
            permission_prompter=self.permission_prompter,
            hook_runner=self.hook_runner,
            session_tracer=self.session_tracer,
            system_prompt=self.system_prompt,
            model=self.model,
            max_iterations=self.max_iterations,
            auto_compaction_threshold=self.auto_compaction_threshold,
            usage_tracker=UsageTracker(),
            on_event=self.on_event,
            on_text_delta=self.on_text_delta,
        )

    def estimated_tokens(self) -> int:
        """Estimate the current token count of the session."""
        return estimate_session_tokens(self.session)

    # -- Preflight check -----------------------------------------------------

    def _preflight_check(self) -> None:
        """Estimate token count and raise if it would exceed the model's context window.

        Uses ~4 chars/token heuristic for the system prompt + messages.
        """
        # Estimate system prompt tokens
        system_tokens = len(self.system_prompt) // 4 if self.system_prompt else 0

        # Estimate message tokens
        message_tokens = estimate_session_tokens(self.session)

        estimated_total = system_tokens + message_tokens

        # Look up context window by model family prefix
        resolved = resolve_model_alias(self.model)
        context_window = 200_000  # default
        for prefix, window in _CONTEXT_WINDOWS.items():
            if resolved.startswith(prefix):
                context_window = window
                break

        # Get max output tokens for the model
        output_tokens = max_tokens_for_model(resolved)

        if estimated_total + output_tokens > context_window:
            raise ContextWindowExceededError(
                f"Estimated {estimated_total} input tokens + {output_tokens} max output tokens "
                f"= {estimated_total + output_tokens} exceeds context window of {context_window} "
                f"for model {resolved}. Consider compacting the session."
            )

    # -- Main turn loop ------------------------------------------------------

    async def run_turn(self, user_input: str) -> TurnSummary:
        """Execute a full model turn with tool loop.

        1. Send user message + history to model
        2. If model requests tools, execute them (with hooks) and loop
        3. Auto-compact if token threshold is exceeded
        4. Return when model produces final text (end_turn)
        """
        self._trace("turn_started", {"user_input_length": len(user_input)})

        self.session.push_user_text(user_input)
        summary = TurnSummary()
        iteration = 0
        cumulative_input_tokens = 0

        # Preflight: ensure we won't exceed the context window
        self._preflight_check()

        try:
            api_messages = self._build_api_messages()

            while iteration < self.max_iterations:
                iteration += 1
                summary.iterations = iteration

                self._trace("assistant_iteration_started", {"iteration": iteration})

                # Stream one model response
                stream_result = await self._stream_model_response(api_messages)

                # Accumulate usage
                summary.usage += stream_result.usage
                self.usage_tracker.record_turn(stream_result.usage)
                cumulative_input_tokens += stream_result.usage.input_tokens

                # Collect prompt cache events
                if stream_result.prompt_cache_event:
                    summary.prompt_cache_events.append(stream_result.prompt_cache_event)

                # Store assistant message in session
                assistant_msg = self._build_assistant_message(
                    stream_result.text_parts, stream_result.tool_uses, stream_result.usage
                )
                if assistant_msg:
                    self.session.push_message(assistant_msg)
                    summary.assistant_messages.append(assistant_msg)

                summary.text_output += stream_result.full_text

                self._trace("assistant_iteration_completed", {
                    "iteration": iteration,
                    "tool_use_count": len(stream_result.tool_uses),
                    "stop_reason": stream_result.stop_reason or "unknown",
                })

                # If no tool uses or stop_reason is end_turn, we're done
                if not stream_result.tool_uses or stream_result.stop_reason == "end_turn":
                    break

                # Execute tools (with full hook integration)
                tool_result_messages = await self._execute_tools_with_hooks(
                    stream_result.tool_uses
                )
                for trm in tool_result_messages:
                    self.session.push_message(trm)
                    summary.tool_results.append(trm)

                # Auto-compaction check
                compaction = self._maybe_auto_compact(cumulative_input_tokens)
                if compaction is not None:
                    summary.compaction_result = compaction
                    summary.was_auto_compacted = True
                    logger.info(
                        "Auto-compacted session: %d -> %d estimated tokens",
                        compaction.estimated_tokens_before,
                        compaction.estimated_tokens_after,
                    )

                # Rebuild API messages for next iteration
                api_messages = self._build_api_messages()

            else:
                # Loop ended without break -- max iterations exceeded
                logger.warning(
                    "Turn reached max iterations (%d)", self.max_iterations
                )

        except Exception as exc:
            self._trace("turn_failed", {"error": str(exc)})
            raise ConversationError(
                f"Turn failed at iteration {iteration}: {exc}", cause=exc
            ) from exc

        self._trace("turn_completed", {
            "iterations": summary.iterations,
            "total_input_tokens": summary.usage.input_tokens,
            "total_output_tokens": summary.usage.output_tokens,
            "was_compacted": summary.was_auto_compacted,
        })

        return summary

    # -- Streaming -----------------------------------------------------------

    @dataclass
    class _StreamResult:
        """Internal: assembled result from one streaming model response."""
        text_parts: list[str] = field(default_factory=list)
        tool_uses: list[dict[str, Any]] = field(default_factory=list)
        usage: TokenUsage = field(default_factory=TokenUsage)
        stop_reason: str | None = None
        prompt_cache_event: PromptCacheEvent | None = None

        @property
        def full_text(self) -> str:
            return "".join(self.text_parts)

    async def _stream_model_response(
        self, api_messages: list[InputMessage]
    ) -> _StreamResult:
        """Stream a single model request and assemble the response."""
        resolved_model = resolve_model_alias(self.model)
        request = MessageRequest(
            model=resolved_model,
            max_tokens=max_tokens_for_model(resolved_model),
            messages=api_messages,
            system=self.system_prompt or None,
            stream=True,
        )

        result = ConversationRuntime._StreamResult()
        current_tool_inputs: dict[int, list[str]] = {}
        current_tool_blocks: dict[int, dict[str, Any]] = {}

        async for event in self.provider.stream_message(request):
            match event:
                case MessageStartEvent(message=msg) if msg is not None:
                    result.usage.input_tokens = msg.usage.input_tokens
                    result.usage.cache_creation_input_tokens = (
                        msg.usage.cache_creation_input_tokens
                    )
                    result.usage.cache_read_input_tokens = (
                        msg.usage.cache_read_input_tokens
                    )
                    # Collect prompt cache event
                    if (
                        msg.usage.cache_creation_input_tokens > 0
                        or msg.usage.cache_read_input_tokens > 0
                    ):
                        result.prompt_cache_event = PromptCacheEvent(
                            cache_creation_input_tokens=msg.usage.cache_creation_input_tokens,
                            cache_read_input_tokens=msg.usage.cache_read_input_tokens,
                            timestamp_ms=int(time.time() * 1000),
                        )

                case ContentBlockStartEvent(index=idx, content_block=block):
                    if isinstance(block, ToolUseOutputBlock):
                        current_tool_blocks[idx] = {
                            "id": block.id,
                            "name": block.name,
                        }
                        current_tool_inputs[idx] = []

                case ContentBlockDeltaEvent(index=idx, delta=delta):
                    if isinstance(delta, TextDelta) and delta.text:
                        result.text_parts.append(delta.text)
                        self._emit_event(AssistantTextDelta(text=delta.text))
                        if self.on_text_delta:
                            self.on_text_delta(delta.text)
                    elif isinstance(delta, InputJsonDelta):
                        if idx in current_tool_inputs:
                            current_tool_inputs[idx].append(delta.partial_json)

                case MessageDeltaEvent(delta=d, usage=u):
                    result.usage.output_tokens = u.output_tokens
                    result.stop_reason = d.stop_reason

                case MessageStopEvent():
                    self._emit_event(
                        AssistantMessageStop(stop_reason=result.stop_reason)
                    )

        # Assemble completed tool uses
        for idx, block_info in current_tool_blocks.items():
            input_json = "".join(current_tool_inputs.get(idx, []))
            tool_use = {
                "id": block_info["id"],
                "name": block_info["name"],
                "input": input_json,
            }
            result.tool_uses.append(tool_use)
            self._emit_event(
                AssistantToolUse(
                    id=tool_use["id"],
                    name=tool_use["name"],
                    input=input_json,
                )
            )

        # Emit usage event
        self._emit_event(AssistantUsage(usage=result.usage))

        # Emit prompt cache event if present
        if result.prompt_cache_event:
            self._emit_event(AssistantPromptCache(
                cache_creation_input_tokens=result.prompt_cache_event.cache_creation_input_tokens,
                cache_read_input_tokens=result.prompt_cache_event.cache_read_input_tokens,
            ))

        return result

    # -- Tool execution with hooks -------------------------------------------

    async def _execute_tools_with_hooks(
        self, tool_uses: list[dict[str, Any]]
    ) -> list[ConversationMessage]:
        """Execute tool calls with full pre/post hook integration."""
        results: list[ConversationMessage] = []

        for tu in tool_uses:
            tool_name = tu["name"]
            tool_input = tu["input"]
            tool_id = tu["id"]

            self._trace("tool_execution_started", {
                "tool_name": tool_name,
                "tool_use_id": tool_id,
            })

            # ---- Phase 1: Pre-tool-use hooks ----
            effective_input = tool_input
            permission_override: PermissionOverride | None = None

            if self.hook_runner:
                pre_result = await self.hook_runner.run_pre_tool_use(
                    tool_name, tool_input
                )

                # Hook denied execution outright
                if pre_result.denied:
                    deny_reason = "; ".join(pre_result.messages) or "Denied by pre-tool-use hook"
                    result_msg = self._make_tool_result(
                        tool_id, tool_name, f"Hook denied: {deny_reason}", is_error=True
                    )
                    results.append(result_msg)
                    self._trace("tool_execution_finished", {
                        "tool_name": tool_name,
                        "tool_use_id": tool_id,
                        "outcome": "hook_denied",
                    })
                    continue

                # Hook may have updated the input
                if pre_result.updated_input is not None:
                    effective_input = pre_result.updated_input
                    logger.debug(
                        "Pre-hook updated input for tool '%s'", tool_name
                    )

                # Hook may have set a permission override
                if pre_result.permission_override is not None:
                    try:
                        permission_override = PermissionOverride(
                            pre_result.permission_override
                        )
                    except ValueError:
                        logger.warning(
                            "Invalid permission_override from hook: %s",
                            pre_result.permission_override,
                        )

            # ---- Phase 2: Permission check ----
            permission_outcome = self._resolve_permission(
                tool_name, effective_input, permission_override
            )
            if isinstance(permission_outcome, PermissionDeny):
                result_msg = self._make_tool_result(
                    tool_id,
                    tool_name,
                    f"Permission denied: {permission_outcome.reason}",
                    is_error=True,
                )
                results.append(result_msg)
                self._trace("tool_execution_finished", {
                    "tool_name": tool_name,
                    "tool_use_id": tool_id,
                    "outcome": "permission_denied",
                })
                continue

            # ---- Phase 3: Execute tool ----
            if self.tool_executor is None:
                output = f"No tool executor configured for '{tool_name}'"
                is_error = True
            else:
                try:
                    output = await self.tool_executor.execute(
                        tool_name, effective_input
                    )
                    is_error = False
                except Exception as exc:
                    output = f"Tool error: {exc}"
                    is_error = True
                    logger.warning("Tool '%s' failed: %s", tool_name, exc)

                    # ---- Phase 3b: Post-tool-use-failure hooks ----
                    if self.hook_runner:
                        fail_result = await self.hook_runner.run_post_tool_use_failure(
                            tool_name, effective_input, str(exc)
                        )
                        if fail_result.messages:
                            output = self._merge_hook_feedback(
                                output, fail_result.messages
                            )

            # ---- Phase 4: Post-tool-use hooks (on success) ----
            if not is_error and self.hook_runner:
                post_result = await self.hook_runner.run_post_tool_use(
                    tool_name, effective_input, output, is_error=False
                )

                # Post-hook can retroactively mark as error
                if post_result.denied:
                    is_error = True
                    deny_reason = (
                        "; ".join(post_result.messages)
                        or "Retroactively denied by post-tool-use hook"
                    )
                    output = f"Post-hook error: {deny_reason}\nOriginal output: {output}"
                elif post_result.messages:
                    output = self._merge_hook_feedback(output, post_result.messages)

            result_msg = self._make_tool_result(
                tool_id, tool_name, output, is_error=is_error
            )
            results.append(result_msg)

            self._trace("tool_execution_finished", {
                "tool_name": tool_name,
                "tool_use_id": tool_id,
                "outcome": "error" if is_error else "success",
            })

        return results

    # -- Permission resolution -----------------------------------------------

    def _resolve_permission(
        self,
        tool_name: str,
        tool_input: str,
        hook_override: PermissionOverride | None,
    ) -> PermissionOutcome:
        """Resolve permission for a tool call, respecting hook overrides.

        Priority:
          1. Hook override (allow/deny/ask)
          2. Interactive prompter (if policy mode is PROMPT and prompter exists)
          3. Policy-based authorization
        """
        if hook_override is not None:
            if hook_override == PermissionOverride.ALLOW:
                return PermissionAllow()
            if hook_override == PermissionOverride.DENY:
                return PermissionDeny(reason="Denied by hook permission override")
            # ASK falls through to normal policy + prompter flow

        return self.permission_policy.authorize(
            tool_name, tool_input, self.permission_prompter
        )

    # -- Auto-compaction -----------------------------------------------------

    def _maybe_auto_compact(self, cumulative_input_tokens: int) -> CompactionResult | None:
        """Check if auto-compaction should trigger and perform it."""
        if cumulative_input_tokens < self.auto_compaction_threshold:
            return None

        config = CompactionConfig(max_tokens=self.auto_compaction_threshold)
        result = compact_session(self.session, config)

        if result is not None:
            self._trace("session_auto_compacted", {
                "tokens_before": result.estimated_tokens_before,
                "tokens_after": result.estimated_tokens_after,
                "removed_count": result.removed_count,
            })

        return result

    # -- Message building helpers --------------------------------------------

    @staticmethod
    def _build_assistant_message(
        text_parts: list[str],
        tool_uses: list[dict[str, Any]],
        usage: TokenUsage,
    ) -> ConversationMessage | None:
        """Assemble an assistant ConversationMessage from streaming output."""
        full_text = "".join(text_parts)
        blocks: list[ContentBlock] = []

        if full_text:
            blocks.append(TextBlock(text=full_text))
        for tu in tool_uses:
            blocks.append(
                ToolUseBlock(id=tu["id"], name=tu["name"], input=tu["input"])
            )

        if not blocks:
            return None

        return ConversationMessage(
            role=MessageRole.ASSISTANT,
            blocks=blocks,
            usage=usage,
        )

    @staticmethod
    def _make_tool_result(
        tool_use_id: str,
        tool_name: str,
        output: str,
        *,
        is_error: bool = False,
    ) -> ConversationMessage:
        """Create a tool-result ConversationMessage."""
        return ConversationMessage(
            role=MessageRole.USER,
            blocks=[
                ToolResultBlock(
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    output=output,
                    is_error=is_error,
                )
            ],
        )

    @staticmethod
    def _merge_hook_feedback(output: str, hook_messages: list[str]) -> str:
        """Merge hook feedback messages into tool output."""
        feedback = "\n".join(f"[hook] {m}" for m in hook_messages if m)
        if not feedback:
            return output
        return f"{output}\n\n{feedback}"

    # -- API message conversion ----------------------------------------------

    def _build_api_messages(self) -> list[InputMessage]:
        """Convert session messages to API input format."""
        from axion.api.types import (
            TextInputBlock,
            ToolResultTextContent,
            ToolUseInputBlock,
        )
        from axion.api.types import (
            ToolResultBlock as ApiToolResultBlock,
        )

        api_messages: list[InputMessage] = []

        for msg in self.session.messages:
            blocks = []
            for block in msg.blocks:
                match block:
                    case TextBlock(text=text):
                        blocks.append(TextInputBlock(text=text))
                    case ToolUseBlock(id=tid, name=name, input=inp):
                        try:
                            parsed = json.loads(inp) if inp else {}
                        except json.JSONDecodeError:
                            parsed = {"raw": inp}
                        blocks.append(
                            ToolUseInputBlock(id=tid, name=name, input=parsed)
                        )
                    case ToolResultBlock() as tr:
                        blocks.append(
                            ApiToolResultBlock(
                                tool_use_id=tr.tool_use_id,
                                content=[ToolResultTextContent(text=tr.output)],
                                is_error=tr.is_error,
                            )
                        )

            if blocks:
                role = "assistant" if msg.role == MessageRole.ASSISTANT else "user"
                api_messages.append(InputMessage(role=role, content=blocks))

        return api_messages

    # -- Tracing / events ----------------------------------------------------

    def _trace(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        """Record a trace event if a session tracer is attached."""
        if self.session_tracer is not None:
            self.session_tracer.record(name, attributes)

    def _emit_event(self, event: AssistantEvent) -> None:
        """Emit an assistant event to the on_event callback."""
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                logger.debug("on_event callback raised", exc_info=True)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _resolve_compaction_threshold() -> int:
    """Resolve auto-compaction threshold from environment or default."""
    raw = os.environ.get(_ENV_COMPACTION_KEY)
    if raw is not None:
        try:
            return int(raw)
        except ValueError:
            logger.warning(
                "Invalid %s value '%s', using default %d",
                _ENV_COMPACTION_KEY,
                raw,
                DEFAULT_AUTO_COMPACTION_THRESHOLD,
            )
    return DEFAULT_AUTO_COMPACTION_THRESHOLD
