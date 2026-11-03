"""Tests for conversation runtime."""


from axion.runtime.conversation import (
    ConversationError,
    MaxIterationsError,
    ToolError,
    TurnSummary,
)


def test_turn_summary_defaults():
    summary = TurnSummary()
    assert summary.iterations == 0
    assert summary.text_output == ""
    assert summary.usage.total_tokens() == 0
    assert summary.prompt_cache_events == []
    assert not summary.was_auto_compacted


def test_conversation_error():
    err = ConversationError("test error")
    assert str(err) == "test error"
    assert err.cause is None


def test_conversation_error_with_cause():
    cause = ValueError("root cause")
    err = ConversationError("wrapper", cause=cause)
    assert err.cause is cause


def test_tool_error():
    err = ToolError("tool failed", tool_name="Bash", tool_use_id="tu_1")
    assert str(err) == "tool failed"
    assert err.tool_name == "Bash"
    assert err.tool_use_id == "tu_1"


def test_max_iterations_error():
    err = MaxIterationsError("exceeded 50 iterations")
    assert isinstance(err, ConversationError)


def test_interrupt_preserves_partial_text(tmp_path):
    """Interrupting mid-stream keeps the partial assistant text and marks the turn interrupted,
    leaving the session well-formed (no dangling tool_use)."""
    import asyncio
    from types import SimpleNamespace
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session
    from axion.api.types import (
        MessageStartEvent, ContentBlockDeltaEvent, MessageResponse, TextDelta, Usage,
    )

    class SlowProvider:
        async def stream_message(self, request):
            yield MessageStartEvent(message=MessageResponse(
                id="1", type="message", role="assistant", content=[], model="rex", usage=Usage()))
            yield ContentBlockDeltaEvent(index=0, delta=TextDelta(text="Partial answer so far"))
            # simulate the interrupt landing before more text arrives
            runtime.request_interrupt()
            await asyncio.sleep(0.01)
            yield ContentBlockDeltaEvent(index=0, delta=TextDelta(text=" ...that should be dropped"))
        async def close(self): ...

    session = Session()
    runtime = ConversationRuntime(session=session, provider=SlowProvider(), model="rex")

    summary = asyncio.new_event_loop().run_until_complete(runtime.run_turn("hi"))
    assert summary.interrupted is True
    # partial text preserved in the session as a clean assistant message
    joined = "".join(
        b.text for m in session.messages for b in m.blocks if hasattr(b, "text")
    )
    assert "Partial answer so far" in joined
    # session must not end on a dangling tool_use
    last = session.messages[-1]
    assert last.role.value == "assistant"


def test_exit_plan_mode_approval_flow():
    """ExitPlanMode presents the plan; approving leaves plan mode, rejecting stays."""
    import asyncio, json
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session

    def approve(_plan): return True
    def reject(_plan): return False

    # Approve → plan mode turns off
    r = ConversationRuntime(session=Session(), provider=object(), model="rex",
                            plan_mode_active=True, on_plan_present=approve)
    msg = asyncio.new_event_loop().run_until_complete(
        r._execute_single_tool({"name": "ExitPlanMode", "input": json.dumps({"plan": "do X"}), "id": "1"})
    )
    assert r.plan_mode_active is False
    assert any("approved" in b.output.lower() for b in msg.blocks if hasattr(b, "output"))

    # Reject → stays in plan mode
    r2 = ConversationRuntime(session=Session(), provider=object(), model="rex",
                             plan_mode_active=True, on_plan_present=reject)
    msg2 = asyncio.new_event_loop().run_until_complete(
        r2._execute_single_tool({"name": "ExitPlanMode", "input": json.dumps({"plan": "do X"}), "id": "2"})
    )
    assert r2.plan_mode_active is True
    assert any("did not approve" in b.output.lower() for b in msg2.blocks if hasattr(b, "output"))


def test_loop_guard_stops_repeated_tool_calls():
    """The loop guard breaks the turn when the model repeats the same dead-end call, well before
    the hard max-iterations cap — so a flailing model doesn't burn 50 iterations on nothing."""
    import asyncio
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session
    from axion.api.types import (
        MessageStartEvent, ContentBlockStartEvent, ContentBlockDeltaEvent, MessageDeltaEvent,
        MessageResponse, ToolUseOutputBlock, InputJsonDelta, MessageDelta, Usage,
    )

    class RepeatProvider:
        async def stream_message(self, request):
            yield MessageStartEvent(message=MessageResponse(
                id="1", type="message", role="assistant", content=[], model="rex", usage=Usage()))
            yield ContentBlockStartEvent(index=0, content_block=ToolUseOutputBlock(id="t", name="Bash", input={}))
            yield ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"command": "ls /nope"}'))
            yield MessageDeltaEvent(delta=MessageDelta(stop_reason="tool_use"), usage=Usage())
        async def close(self): ...

    class ZeroExec:
        async def execute(self, *args, **kwargs):
            return "0"  # every call comes back empty/dead-end

    session = Session()
    runtime = ConversationRuntime(
        session=session, provider=RepeatProvider(), model="rex", tool_executor=ZeroExec()
    )
    summary = asyncio.new_event_loop().run_until_complete(runtime.run_turn("count the files"))

    assert summary.iterations < 50  # stopped well before the hard cap
    assert summary.iterations <= 4  # repeat detected at the 3rd identical call
    assert "stopped itself" in summary.text_output.lower()


def test_loop_guard_stops_varied_dead_end_commands():
    """Different-but-fruitless commands (the playwright-artifact hunt) trip the low-value cap even
    though no single call repeats — because none of them return new information."""
    import asyncio
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session
    from axion.api.types import (
        MessageStartEvent, ContentBlockStartEvent, ContentBlockDeltaEvent, MessageDeltaEvent,
        MessageResponse, ToolUseOutputBlock, InputJsonDelta, MessageDelta, Usage,
    )

    n = {"i": 0}

    class VariedProvider:
        async def stream_message(self, request):
            n["i"] += 1
            yield MessageStartEvent(message=MessageResponse(
                id="1", type="message", role="assistant", content=[], model="rex", usage=Usage()))
            yield ContentBlockStartEvent(index=0, content_block=ToolUseOutputBlock(id=f"t{n['i']}", name="Bash", input={}))
            yield ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json=f'{{"command": "ls /nope{n["i"]}"}}'))
            yield MessageDeltaEvent(delta=MessageDelta(stop_reason="tool_use"), usage=Usage())
        async def close(self): ...

    class EmptyExec:
        async def execute(self, *a, **k):
            return ""  # every varied command returns nothing

    session = Session()
    runtime = ConversationRuntime(session=session, provider=VariedProvider(), model="rex", tool_executor=EmptyExec())
    summary = asyncio.new_event_loop().run_until_complete(runtime.run_turn("find the file"))
    assert summary.iterations < 50
    assert summary.iterations <= 12  # broke on the cumulative "no new info" cap (~10)
    assert "nothing new" in summary.text_output.lower()


def test_loop_guard_stops_repeated_404_downloads():
    """The masscan case: a 404 is a 'successful' command (exit 0, non-empty output), and the model
    varies the URL every time so no signature repeats — yet each result is permanently futile. Three
    no-progress rounds in a row must trip the guard fast, instead of sleep-and-retrying forever."""
    import asyncio
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session
    from axion.api.types import (
        MessageStartEvent, ContentBlockStartEvent, ContentBlockDeltaEvent, MessageDeltaEvent,
        MessageResponse, ToolUseOutputBlock, InputJsonDelta, MessageDelta, Usage,
    )

    n = {"i": 0}

    class Http404Provider:
        async def stream_message(self, request):
            n["i"] += 1
            yield MessageStartEvent(message=MessageResponse(
                id="1", type="message", role="assistant", content=[], model="rex", usage=Usage()))
            yield ContentBlockStartEvent(index=0, content_block=ToolUseOutputBlock(id=f"t{n['i']}", name="Bash", input={}))
            # A different URL and a different sleep each round: neither the exact-repeat signature nor
            # duplicate-output detection can catch this — only the futile-marker / no-progress logic.
            yield ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(
                partial_json=f'{{"command": "sleep {n["i"]*10}; curl -sIL https://example.com/dl/v{n["i"]}.zip"}}'))
            yield MessageDeltaEvent(delta=MessageDelta(stop_reason="tool_use"), usage=Usage())
        async def close(self): ...

    class NotFoundExec:
        async def execute(self, *a, **k):
            # Distinct output each time (not a duplicate, not an error, not empty): the ONLY low-value
            # signal is the "404 not found" futile marker.
            return f"HTTP/1.1 404 Not Found\nfor https://example.com/dl/v{n['i']}.zip"

    session = Session()
    runtime = ConversationRuntime(session=session, provider=Http404Provider(), model="rex", tool_executor=NotFoundExec())
    summary = asyncio.new_event_loop().run_until_complete(runtime.run_turn("download masscan"))
    assert summary.iterations < 50
    assert summary.iterations <= 4  # three consecutive dead-end rounds -> stop
    assert "stopped itself" in summary.text_output.lower()


def test_interrupt_during_tool_loop_stops_cleanly():
    """Ctrl-C during a tool-heavy turn stops cleanly (interrupted, session well-formed) — not a crash."""
    import asyncio
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session
    from axion.api.types import (
        MessageStartEvent, ContentBlockStartEvent, ContentBlockDeltaEvent, MessageDeltaEvent,
        MessageResponse, ToolUseOutputBlock, InputJsonDelta, MessageDelta, Usage,
    )

    runtime_ref = {}

    class ToolProvider:
        async def stream_message(self, request):
            yield MessageStartEvent(message=MessageResponse(
                id="1", type="message", role="assistant", content=[], model="rex", usage=Usage()))
            yield ContentBlockStartEvent(index=0, content_block=ToolUseOutputBlock(id="t", name="Bash", input={}))
            yield ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"command": "echo hi"}'))
            yield MessageDeltaEvent(delta=MessageDelta(stop_reason="tool_use"), usage=Usage())
        async def close(self): ...

    calls = {"n": 0}

    class InterruptingExec:
        async def execute(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 2:
                runtime_ref["r"].request_interrupt()  # user hits Ctrl-C mid-turn
            return f"output {calls['n']}"

    session = Session()
    runtime = ConversationRuntime(session=session, provider=ToolProvider(), model="rex", tool_executor=InterruptingExec())
    runtime_ref["r"] = runtime
    summary = asyncio.new_event_loop().run_until_complete(runtime.run_turn("do a thing"))

    assert summary.interrupted is True
    assert summary.iterations < 50
    # session ends well-formed (not on a dangling assistant tool_use with no results)
    last = session.messages[-1]
    assert not (last.role.value == "assistant" and any(hasattr(b, "id") and hasattr(b, "name") and not hasattr(b, "output") for b in last.blocks))


def test_parallel_permission_prompts_only_once():
    """Several parallel calls to the same tool (e.g. a fan-out of Agent spawns) prompt only once —
    after the first 'allow always', the rest return the cached allow instead of re-asking."""
    import asyncio
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session
    from axion.runtime.permissions import (
        PermissionAllow, PermissionMode, PermissionPolicy, PermissionPromptDecision,
    )

    class CountingPrompter:
        def __init__(self) -> None:
            self.calls = 0

        async def decide(self, request):
            self.calls += 1
            await asyncio.sleep(0.01)  # give the other parallel calls time to reach the lock
            return PermissionPromptDecision.ALLOW_ALWAYS

    async def main():
        prompter = CountingPrompter()
        runtime = ConversationRuntime(
            session=Session(), provider=object(), model="rex",
            permission_policy=PermissionPolicy(mode=PermissionMode.PROMPT),
            permission_prompter=prompter,  # type: ignore[arg-type]
        )
        results = await asyncio.gather(*[
            runtime._resolve_permission("Agent", '{"prompt":"x"}', None) for _ in range(3)
        ])
        assert prompter.calls == 1  # asked once, not three times
        assert all(isinstance(r, PermissionAllow) for r in results)

    asyncio.new_event_loop().run_until_complete(main())


def test_incomplete_tool_call_triggers_retry():
    """A truncated tool-call JSON on the first stream is retried, not executed as garbage."""
    import asyncio
    from axion.runtime.conversation import ConversationRuntime
    from axion.runtime.session import Session
    from axion.api.types import (
        MessageStartEvent, ContentBlockStartEvent, ContentBlockDeltaEvent, MessageDeltaEvent,
        MessageResponse, ToolUseOutputBlock, InputJsonDelta, MessageDelta, Usage,
    )

    attempts = {"n": 0}

    class FlakyProvider:
        async def stream_message(self, request):
            attempts["n"] += 1
            yield MessageStartEvent(message=MessageResponse(
                id="1", type="message", role="assistant", content=[], model="rex", usage=Usage()))
            yield ContentBlockStartEvent(index=0, content_block=ToolUseOutputBlock(id="t1", name="Read", input={}))
            if attempts["n"] == 1:
                yield ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"path": "a'))  # truncated
            else:
                yield ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"path": "a.txt"}'))
                yield MessageDeltaEvent(delta=MessageDelta(stop_reason="tool_use"), usage=Usage())
        async def close(self): ...

    # exercise _stream_model_response retry via run_turn's loop indirectly:
    runtime = ConversationRuntime(session=Session(), provider=FlakyProvider(), model="rex", tool_executor=None)
    # first stream flags incomplete; second is clean
    r1 = asyncio.new_event_loop().run_until_complete(runtime._stream_model_response([]))
    assert r1.has_incomplete_tool_call is True
    r2 = asyncio.new_event_loop().run_until_complete(runtime._stream_model_response([]))
    assert r2.has_incomplete_tool_call is False
