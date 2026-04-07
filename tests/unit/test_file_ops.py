"""Tests for file operations."""


import pytest

from axion.runtime.file_ops import (
    edit_file,
    glob_search,
    grep_search,
    is_binary_file,
    read_file,
    write_file,
)


def test_read_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("line1\nline2\nline3\n")
    result = read_file(str(f))
    assert result.num_lines == 3
    assert result.total_lines == 3
    assert "line1" in result.content


def test_read_file_with_range(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("\n".join(f"line{i}" for i in range(1, 11)))
    result = read_file(str(f), start_line=3, end_line=5)
    assert result.num_lines == 3
    assert "line3" in result.content
    assert "line1" not in result.content


def test_read_file_not_found():
    with pytest.raises(FileNotFoundError):
        read_file("/nonexistent/file.txt")


def test_read_file_too_large(tmp_path):
    f = tmp_path / "big.txt"
    f.write_bytes(b"x" * (11 * 1024 * 1024))
    with pytest.raises(ValueError, match="too large"):
        read_file(str(f))


def test_read_binary_file(tmp_path):
    f = tmp_path / "binary.bin"
    f.write_bytes(b"\x00\x01\x02\x03")
    with pytest.raises(ValueError, match="Binary file"):
        read_file(str(f))


def test_is_binary_file(tmp_path):
    text_file = tmp_path / "text.txt"
    text_file.write_text("hello world")
    assert not is_binary_file(text_file)

    bin_file = tmp_path / "data.bin"
    bin_file.write_bytes(b"hello\x00world")
    assert is_binary_file(bin_file)


def test_write_file_create(tmp_path):
    f = tmp_path / "new.txt"
    result = write_file(str(f), "hello world")
    assert result.kind == "create"
    assert f.read_text() == "hello world"


def test_write_file_update(tmp_path):
    f = tmp_path / "existing.txt"
    f.write_text("old content")
    result = write_file(str(f), "new content")
    assert result.kind == "update"
    assert result.original_file == "old content"
    assert len(result.structured_patch) > 0


def test_edit_file(tmp_path):
    f = tmp_path / "code.py"
    f.write_text("def foo():\n    return 1\n")
    result = edit_file(str(f), "return 1", "return 42")
    assert result.replacements == 1
    assert "return 42" in f.read_text()


def test_edit_file_identical_strings(tmp_path):
    f = tmp_path / "same.txt"
    f.write_text("same content")
    with pytest.raises(ValueError, match="identical"):
        edit_file(str(f), "same", "same")


def test_edit_file_ambiguous(tmp_path):
    f = tmp_path / "dups.txt"
    f.write_text("x = 1\nx = 1\n")
    with pytest.raises(ValueError, match="appears 2 times"):
        edit_file(str(f), "x = 1", "x = 2")


def test_edit_file_replace_all(tmp_path):
    f = tmp_path / "dups.txt"
    f.write_text("x = 1\nx = 1\n")
    result = edit_file(str(f), "x = 1", "x = 2", replace_all=True)
    assert result.replacements == 2
    assert f.read_text() == "x = 2\nx = 2\n"


def test_glob_search(tmp_path):
    (tmp_path / "a.py").write_text("hello")
    (tmp_path / "b.py").write_text("world")
    (tmp_path / "c.txt").write_text("other")
    result = glob_search("*.py", path=str(tmp_path))
    assert result.num_files == 2


def test_grep_search(tmp_path):
    (tmp_path / "a.py").write_text("def foo():\n    return 42\n")
    (tmp_path / "b.py").write_text("def bar():\n    return 0\n")
    result = grep_search("return 42", path=str(tmp_path))
    assert result.num_matches >= 1
    assert any("a.py" in m.file for m in result.matches)


def test_grep_case_insensitive(tmp_path):
    (tmp_path / "test.py").write_text("Hello World\n")
    result = grep_search("hello", path=str(tmp_path), case_insensitive=True)
    assert result.num_matches >= 1
