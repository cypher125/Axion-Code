"""Tests for tool registry."""

from axion.tools.registry import (
    GlobalToolRegistry,
    get_tool_registry,
    BASH_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    EDIT_TOOL,
    GLOB_TOOL,
    GREP_TOOL,
)


def test_global_registry_has_builtins():
    registry = get_tool_registry()
    names = registry.tool_names()
    assert "Bash" in names
    assert "Read" in names
    assert "Write" in names
    assert "Edit" in names
    assert "Glob" in names
    assert "Grep" in names
    assert "WebSearch" in names
    assert "WebFetch" in names


def test_registry_get():
    registry = GlobalToolRegistry()
    bash = registry.get("Bash")
    assert bash is not None
    assert bash.spec.name == "Bash"
    assert bash.source == "builtin"


def test_registry_to_api_tools():
    registry = GlobalToolRegistry()
    tools = registry.to_api_tools()
    assert len(tools) >= 8
    names = [t["name"] for t in tools]
    assert "Bash" in names
    assert "Read" in names


def test_tool_specs_have_schemas():
    for tool_spec in [BASH_TOOL, READ_TOOL, WRITE_TOOL, EDIT_TOOL, GLOB_TOOL, GREP_TOOL]:
        assert tool_spec.name
        assert tool_spec.description
        assert tool_spec.input_schema
        assert tool_spec.input_schema["type"] == "object"
        assert "properties" in tool_spec.input_schema
