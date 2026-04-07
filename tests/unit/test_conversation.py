"""Tests for conversation runtime."""

import pytest

from axion.runtime.conversation import (
    ConversationError,
    ConversationRuntime,
    MaxIterationsError,
    ToolError,
    TurnSummary,
    ToolExecutor,
)
from axion.runtime.session import Session


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
