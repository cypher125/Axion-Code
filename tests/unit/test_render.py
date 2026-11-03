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


def test_push_stream_streams_each_completed_line():
    """Line-granular streaming: each completed line surfaces immediately; the partial line waits."""
    stream = MarkdownStreamState()

    # A completed prose line streams the moment its newline arrives.
    segs = stream.push_stream("First line\n")
    assert segs == [("md", "First line")]

    # No newline yet -> nothing emitted (the partial line is held).
    assert stream.push_stream("partial ") == []
    # Newline completes it.
    assert stream.push_stream("done\n") == [("md", "partial done")]


def test_push_stream_code_fence_lines_are_raw_and_live():
    """Code inside a ``` fence streams line by line as raw text (not held until the fence closes)."""
    stream = MarkdownStreamState()
    segs = stream.push_stream("Here:\n```python\ndef foo():\n    return 1\n```\nafter\n")
    assert segs == [
        ("md", "Here:"),
        ("raw", "```python"),   # fence delimiter
        ("raw", "def foo():"),  # code line — emitted before the fence closed
        ("raw", "    return 1"),
        ("raw", "```"),
        ("md", "after"),
    ]


def test_flush_stream_emits_trailing_partial():
    stream = MarkdownStreamState()
    stream.push_stream("no newline here")
    assert stream.flush_stream() == [("md", "no newline here")]
    assert stream.flush_stream() == []  # nothing left


def test_live_streamer_emits_completed_lines_and_tail(monkeypatch):
    """LiveStreamer streams completed lines via the callback and flushes the trailing partial.

    Forces the Live-disabled ('lines') path so behaviour is deterministic without a real terminal.
    """
    from axion.cli.render import LiveStreamer

    monkeypatch.setenv("AXION_STREAM", "lines")
    console = Console()
    got: list[tuple[str, str]] = []
    state = MarkdownStreamState()
    s = LiveStreamer(console, state, lambda kind, line: got.append((kind, line)))

    s.push("Hello ")
    assert got == []  # incomplete line held back
    s.push("world\nleftover")
    assert got == [("md", "Hello world")]  # completed line streamed
    assert s.finish() is True  # trailing partial flushed
    assert got[-1] == ("md", "leftover")
    assert s.finish() is False  # nothing left; idempotent


def test_agent_dashboard_tracks_each_agent():
    """The multi-agent dashboard shows every agent, its live action, tokens, and final status.

    Exercises the non-live fallback (deterministic without a VT terminal); the live Rich table is
    the same data rendered in place on a VT-capable terminal.
    """
    import io

    from axion.cli.agent_dashboard import AgentDashboard

    buf = io.StringIO()
    d = AgentDashboard(console=Console(file=buf, force_terminal=False))
    d.register("recon:host-1", "recon")
    d.register("web:app", "web-pentester")
    d.update("recon:host-1", action="nmap -sV 10.0.0.5")
    d.update("web:app", action="browser_click Login")
    d.finish("recon:host-1", tokens=1240, ok=True, note="done")
    d.finish("web:app", ok=False, note="failed")
    out = buf.getvalue()

    assert "recon:host-1" in out and "web:app" in out  # labels survive (markup disabled)
    assert "nmap -sV 10.0.0.5" in out
    assert "1,240" in out
    assert "failed" in out
    # The live table renderable builds without error too.
    assert d._table() is not None


def test_terminal_renderer_methods():
    console = Console(force_terminal=True, width=80)
    renderer = TerminalRenderer(console=console)
    # Just verify methods don't crash
    renderer.render_text("hello")
    renderer.render_error("bad")
    renderer.render_warning("watch out")
    renderer.render_info("fyi")
    renderer.render_separator()
