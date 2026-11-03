"""Tests for tool registry."""

from axion.tools.registry import (
    BASH_TOOL,
    EDIT_TOOL,
    GLOB_TOOL,
    GREP_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    GlobalToolRegistry,
    get_tool_registry,
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


def test_cap_tool_result(monkeypatch):
    """A single oversized tool result is truncated to the configured char budget."""
    from axion.tools.registry import _cap_tool_result

    monkeypatch.setenv("AXION_MAX_TOOL_RESULT_CHARS", "1000")
    big = "y" * 50_000
    out = _cap_tool_result(big)
    assert len(out) < 1300  # ~1000 budget + the truncation notice
    assert "truncated to fit the context window" in out
    # Small results pass through untouched
    assert _cap_tool_result("short") == "short"
    # 0 disables the cap
    monkeypatch.setenv("AXION_MAX_TOOL_RESULT_CHARS", "0")
    assert _cap_tool_result(big) == big


def test_multi_edit_atomic(tmp_path):
    import asyncio

    from axion.tools.registry import BuiltinToolExecutor, get_tool_registry
    assert "MultiEdit" in [t["name"] for t in get_tool_registry().to_api_tools()]
    f = tmp_path / "code.py"
    f.write_text("alpha\nbeta\ngamma\n", encoding="utf-8")
    ex = BuiltinToolExecutor(cwd=str(tmp_path))
    loop = asyncio.new_event_loop()
    # Successful multi-edit
    out = loop.run_until_complete(ex.execute("MultiEdit", '{"file_path": "%s", "edits": [{"old_string":"alpha","new_string":"A"},{"old_string":"gamma","new_string":"G"}]}' % str(f).replace("\\","\\\\")))
    assert "Applied 2" in out
    assert f.read_text(encoding="utf-8") == "A\nbeta\nG\n"
    # Atomic failure: second edit doesn't match -> file unchanged from previous state
    before = f.read_text(encoding="utf-8")
    out2 = loop.run_until_complete(ex.execute("MultiEdit", '{"file_path": "%s", "edits": [{"old_string":"A","new_string":"X"},{"old_string":"NOPE","new_string":"Y"}]}' % str(f).replace("\\","\\\\")))
    assert "error: edit 2" in out2
    assert f.read_text(encoding="utf-8") == before  # nothing written
    loop.close()


def test_ssrf_blocks_internal_hosts():
    from axion.tools.registry import _ssrf_block_reason
    assert _ssrf_block_reason("http://169.254.169.254/latest/meta-data/")  # cloud metadata
    assert _ssrf_block_reason("http://127.0.0.1:8000/admin")               # loopback
    assert _ssrf_block_reason("http://localhost/")                         # loopback name
    assert _ssrf_block_reason("file:///etc/passwd")                        # bad scheme
    # a public host must NOT be blocked (uses a documentation IP via a resolvable name)
    assert _ssrf_block_reason("https://example.com/") is None


def test_workspace_write_confines_paths(tmp_path):
    from axion.tools.registry import BuiltinToolExecutor
    ex = BuiltinToolExecutor(cwd=str(tmp_path), permission_mode="workspace-write")
    # inside the workspace: allowed (None)
    assert ex._confine_path_error(str(tmp_path / "ok.txt")) is None
    # outside the workspace: blocked
    outside = str(tmp_path.parent / "sneaky.txt")
    assert ex._confine_path_error(outside) is not None
    # danger-full-access: unrestricted
    ex2 = BuiltinToolExecutor(cwd=str(tmp_path), permission_mode="danger-full-access")
    assert ex2._confine_path_error(outside) is None


def test_sub_agent_inherits_permission_mode():
    from axion.tools.registry import BuiltinToolExecutor
    ex = BuiltinToolExecutor(cwd=".", permission_mode="read-only")
    assert ex.permission_mode == "read-only"


def test_edit_shows_diff(tmp_path):
    import asyncio

    from axion.tools.registry import BuiltinToolExecutor
    f = tmp_path / "f.txt"
    f.write_text("one\ntwo\nthree\n", encoding="utf-8")
    ex = BuiltinToolExecutor(cwd=str(tmp_path), permission_mode="danger-full-access")
    out = asyncio.new_event_loop().run_until_complete(
        ex.execute("Edit", '{"file_path": "%s", "old_string": "two", "new_string": "TWO"}' % str(f).replace("\\","\\\\"))
    )
    assert "Replaced 1" in out
    assert "-two" in out and "+TWO" in out  # unified diff shown


def test_agent_typed_roles_defined():
    from axion.tools.registry import AGENT_TYPES
    assert AGENT_TYPES["explore"]["mode"] == "read-only"
    assert AGENT_TYPES["plan"]["mode"] == "read-only"
    assert AGENT_TYPES["general"]["mode"] is None  # inherits parent
    # explore/plan carry a role prompt; general does not
    assert AGENT_TYPES["explore"]["prompt"] and not AGENT_TYPES["general"]["prompt"]


def test_custom_agent_types_loaded(tmp_path):
    from axion.tools.registry import load_custom_agent_types
    agents_dir = tmp_path / ".axion" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "reviewer.md").write_text(
        "---\nname: reviewer\ndescription: reviews code\nmode: read-only\n---\n"
        "You are a strict code reviewer. Only read; never modify.",
        encoding="utf-8",
    )
    types = load_custom_agent_types(str(tmp_path))
    assert "reviewer" in types
    assert types["reviewer"]["mode"] == "read-only"
    assert "strict code reviewer" in types["reviewer"]["prompt"]


def test_subagent_progress_and_types_merge(monkeypatch, tmp_path):
    # custom role name resolves (falls back to general if absent)
    from axion.tools.registry import AGENT_TYPES, load_custom_agent_types
    merged = {**AGENT_TYPES, **load_custom_agent_types(str(tmp_path))}
    assert merged["general"]["mode"] is None
    assert "explore" in merged and "plan" in merged
