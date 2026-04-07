"""Tests for ToolSearch - deferred tool schema loading."""

from axion.tools.tool_search import (
    DeferredToolRegistry,
    ToolSearchOutput,
    tool_search,
)
from axion.tools.registry import GlobalToolRegistry


def test_search_by_keyword():
    result = tool_search("bash")
    assert isinstance(result, ToolSearchOutput)
    assert len(result.results) >= 1
    assert any(r.name == "Bash" for r in result.results)


def test_search_by_keyword_grep():
    result = tool_search("search content")
    assert len(result.results) >= 1
    names = [r.name for r in result.results]
    assert "Grep" in names or "WebSearch" in names


def test_select_single():
    result = tool_search("select:Read")
    assert len(result.schemas) == 1
    assert result.schemas[0]["name"] == "Read"
    assert "input_schema" in result.schemas[0]


def test_select_multiple():
    result = tool_search("select:Read,Write,Edit")
    assert len(result.schemas) == 3
    names = [s["name"] for s in result.schemas]
    assert "Read" in names
    assert "Write" in names
    assert "Edit" in names


def test_select_not_found():
    result = tool_search("select:NonexistentTool")
    assert len(result.schemas) == 0
    assert "Not found" in result.message


def test_search_no_results():
    result = tool_search("xyznonexistent12345")
    assert len(result.results) == 0


def test_search_max_results():
    result = tool_search("tool", max_results=2)
    assert len(result.results) <= 2


def test_deferred_registry():
    reg = GlobalToolRegistry()
    deferred = DeferredToolRegistry(reg)

    deferred.defer_tool("Read")
    assert "Read" in deferred.deferred_tool_names()
    assert not deferred.is_active("Read")

    spec = deferred.activate_tool("Read")
    assert spec is not None
    assert spec.name == "Read"
    assert deferred.is_active("Read")
    assert "Read" not in deferred.deferred_tool_names()
