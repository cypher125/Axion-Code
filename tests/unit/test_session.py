"""Tests for session persistence."""


from axion.runtime.session import (
    ConversationMessage,
    MessageRole,
    Session,
    TextBlock,
    ToolUseBlock,
)
from axion.runtime.usage import TokenUsage


def test_session_create():
    session = Session()
    assert session.version == 1
    assert len(session.session_id) == 16
    assert session.messages == []


def test_push_user_text():
    session = Session()
    session.push_user_text("Hello")
    assert len(session.messages) == 1
    assert session.messages[0].role == MessageRole.USER
    assert isinstance(session.messages[0].blocks[0], TextBlock)
    assert session.messages[0].blocks[0].text == "Hello"


def test_push_assistant_text():
    session = Session()
    usage = TokenUsage(input_tokens=10, output_tokens=20)
    session.push_assistant_text("Hi there", usage=usage)
    assert len(session.messages) == 1
    assert session.messages[0].role == MessageRole.ASSISTANT
    assert session.messages[0].usage.input_tokens == 10


def test_session_save_and_load(tmp_path):
    session = Session()
    session.push_user_text("Hello")
    session.push_assistant_text("Hi")

    path = tmp_path / "test_session.jsonl"
    session.save(path)
    assert path.exists()

    loaded = Session.load(path)
    assert loaded.session_id == session.session_id
    assert len(loaded.messages) == 2
    assert loaded.messages[0].role == MessageRole.USER


def test_title_persists(tmp_path):
    session = Session()
    session.push_user_text("hi")
    session.title = "Playwright MCP setup"
    path = tmp_path / "titled.jsonl"
    session.save(path)
    assert Session.load(path).title == "Playwright MCP setup"


def _write(tmp_path, name, session):
    p = tmp_path / f"{name}.jsonl"
    session.save(p)
    return p


def test_session_title_skips_greetings_and_uses_summary(tmp_path):
    from axion.cli.main import _session_title
    from axion.runtime.session import SessionCompaction

    # Greeting first, real ask second -> the real ask is the title.
    s = Session()
    s.push_user_text("hey Rex")
    s.push_assistant_text("hi")
    s.push_user_text("audit the permissions code for escalation bugs")
    assert _session_title(_write(tmp_path, "a", s)) == "audit the permissions code for escalation bugs"

    # A compacted session is titled by its summary, not the "[Session compacted…]" marker.
    s2 = Session(compaction=SessionCompaction(count=1, removed_message_count=37, summary="x"))
    s2.push_user_text("[Session compacted. Summary of 37 earlier messages:]\nDebugged why compaction never fired on the A10 tier.")
    title = _session_title(_write(tmp_path, "b", s2))
    assert not title.startswith("[Session compacted")
    assert "compaction never fired" in title

    # An explicit /rename title always wins.
    s3 = Session(title="My named session")
    s3.push_user_text("whatever")
    assert _session_title(_write(tmp_path, "c", s3)) == "My named session"


def test_conversation_message_roundtrip():
    msg = ConversationMessage(
        role=MessageRole.ASSISTANT,
        blocks=[
            TextBlock(text="Let me help"),
            ToolUseBlock(id="tu_1", name="Read", input='{"file_path": "/tmp/test"}'),
        ],
        usage=TokenUsage(input_tokens=100, output_tokens=50),
    )
    d = msg.to_dict()
    restored = ConversationMessage.from_dict(d)
    assert restored.role == MessageRole.ASSISTANT
    assert len(restored.blocks) == 2
    assert isinstance(restored.blocks[0], TextBlock)
    assert isinstance(restored.blocks[1], ToolUseBlock)
    assert restored.usage.input_tokens == 100


def test_message_count():
    session = Session()
    assert session.message_count() == 0
    session.push_user_text("one")
    session.push_user_text("two")
    assert session.message_count() == 2


def test_rotate_survives_many_rotations_and_bounds_count(tmp_path):
    """Rotation must not crash on Windows-style rename-over-existing and must cap rotated files."""
    from axion.runtime.session import MAX_ROTATED_FILES, Session

    base = tmp_path / "s.jsonl"
    base.write_text("orig", encoding="utf-8")
    for n in range(MAX_ROTATED_FILES + 3):
        base.write_text(f"gen{n}", encoding="utf-8")
        Session._rotate(base)  # must not raise
    rotated = sorted(tmp_path.glob("s.*.jsonl"))
    assert len(rotated) <= MAX_ROTATED_FILES, f"too many rotated files: {rotated}"


def test_rewind_removes_last_user_turn():
    from axion.cli.main import _rewind_session
    from axion.runtime.session import (
        ConversationMessage,
        MessageRole,
        Session,
        TextBlock,
        ToolResultBlock,
        ToolUseBlock,
    )
    s = Session()
    # turn 1: user, assistant(tool), tool_result
    s.push_message(ConversationMessage(role=MessageRole.USER, blocks=[TextBlock(text="do A")]))
    s.push_message(ConversationMessage(role=MessageRole.ASSISTANT, blocks=[ToolUseBlock(id="t", name="R", input="{}")]))
    s.push_message(ConversationMessage(role=MessageRole.USER, blocks=[ToolResultBlock(tool_use_id="t", tool_name="R", output="x")]))
    s.push_message(ConversationMessage(role=MessageRole.ASSISTANT, blocks=[TextBlock(text="done A")]))
    # turn 2: user, assistant
    s.push_message(ConversationMessage(role=MessageRole.USER, blocks=[TextBlock(text="do B")]))
    s.push_message(ConversationMessage(role=MessageRole.ASSISTANT, blocks=[TextBlock(text="done B")]))
    assert len(s.messages) == 6
    removed = _rewind_session(s, 1)
    assert removed == 2  # user "do B" + assistant "done B"
    assert len(s.messages) == 4
    # rewinding again removes turn 1 entirely (4 messages)
    removed2 = _rewind_session(s, 1)
    assert removed2 == 4 and len(s.messages) == 0
