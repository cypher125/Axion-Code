"""Tests for terminal renderer."""

from rich.console import Console

from axion.cli.render import (
    MarkdownStreamState,
    TerminalRenderer,
    format_tool_call_start,
    format_tool_result,
)


def test_format_tool_call_bash():
    result = format_tool_call_start("Bash", '{"command": "ls -la"}')
    assert "Bash" in result
    assert "ls -la" in result
    assert "╭" in result


def test_format_tool_call_read():
    result = format_tool_call_start("Read", '{"file_path": "/tmp/test.py"}')
    assert "Read" in result
    assert "/tmp/test.py" in result


def test_format_tool_call_empty_input():
    result = format_tool_call_start("Agent", "")
    assert "Agent" in result


def test_format_tool_result_success():
    result = format_tool_result("Bash", "hello world")
    assert "✓" in result
    assert "hello world" in result
    assert "╰" in result


def test_format_tool_result_error():
    result = format_tool_result("Bash", "command not found", is_error=True)
    assert "✗" in result
    assert "error" in result


def test_format_tool_result_truncation():
    long_output = "x" * 5000
    result = format_tool_result("Read", long_output)
    assert "truncated" in result


def test_markdown_stream_state():
    renderer = TerminalRenderer(console=Console(force_terminal=True, width=80))
    stream = MarkdownStreamState()

    # Push text without safe boundary
    result = stream.push(renderer, "Hello, ")
    assert result is None  # No safe boundary

    # Push text with blank line (safe boundary)
    result = stream.push(renderer, "world!\n\nMore text")
    assert result is not None
    assert "Hello" in result


def test_markdown_stream_code_fence():
    renderer = TerminalRenderer()
    stream = MarkdownStreamState()

    # Push start of code block — should NOT split inside
    result = stream.push(renderer, "```python\ndef foo():\n")
    assert result is None  # Inside code fence, not safe

    # End code block
    result = stream.push(renderer, "    pass\n```\n\nMore")
    assert result is not None  # Safe after fence closes


def test_terminal_renderer_methods():
    console = Console(force_terminal=True, width=80)
    renderer = TerminalRenderer(console=console)
    # Just verify methods don't crash
    renderer.render_text("hello")
    renderer.render_error("bad")
    renderer.render_warning("watch out")
    renderer.render_info("fyi")
    renderer.render_separator()
