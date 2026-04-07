"""Tests for memory system."""

from claw.runtime.memory import MemoryEntry, MemoryStore, MemoryType


def test_memory_save_and_load(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    entry = MemoryEntry(
        name="user-role",
        description="User is a senior engineer",
        type=MemoryType.USER,
        content="The user is a senior Python developer focused on backend.",
    )
    store.save(entry)

    loaded = store.load("user-role")
    assert loaded is not None
    assert loaded.name == "user-role"
    assert loaded.type == MemoryType.USER
    assert "senior Python" in loaded.content


def test_memory_load_all(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    store.save(MemoryEntry(name="a", description="first", type=MemoryType.USER, content="A"))
    store.save(MemoryEntry(name="b", description="second", type=MemoryType.FEEDBACK, content="B"))

    all_entries = store.load_all()
    assert len(all_entries) == 2
    names = {e.name for e in all_entries}
    assert names == {"a", "b"}


def test_memory_remove(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    store.save(MemoryEntry(name="temp", description="temp", type=MemoryType.PROJECT, content="X"))
    assert store.load("temp") is not None

    store.remove("temp")
    assert store.load("temp") is None


def test_memory_index(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    store.save(MemoryEntry(name="entry1", description="First entry", type=MemoryType.USER, content="A"))
    store.save(MemoryEntry(name="entry2", description="Second entry", type=MemoryType.FEEDBACK, content="B"))

    entries = store.load_all()
    store.save_index(entries)

    index = store.load_index()
    assert index is not None
    assert "entry1" in index
    assert "entry2" in index


def test_memory_update(tmp_path):
    store = MemoryStore(memory_dir=tmp_path)
    store.save(MemoryEntry(name="evolving", description="v1", type=MemoryType.USER, content="version 1"))
    store.save(MemoryEntry(name="evolving", description="v2", type=MemoryType.USER, content="version 2"))

    loaded = store.load("evolving")
    assert loaded is not None
    assert loaded.description == "v2"
    assert "version 2" in loaded.content
