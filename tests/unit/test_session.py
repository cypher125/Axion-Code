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
