"""Global tool registry and tool definitions.

Maps to: rust/crates/tools/src/lib.rs
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from claw.runtime.bash import BashCommandInput, execute_bash
from claw.runtime.file_ops import (
    edit_file,
    glob_search,
    grep_search,
    read_file,
    write_file,
)

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    """Specification for a single tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    required_permission: str = "read-only"


@dataclass
class RuntimeToolDefinition:
    """A tool definition with its spec and source information."""

    spec: ToolSpec
    source: str = "builtin"


# ---------------------------------------------------------------------------
# Built-in tool specifications
# ---------------------------------------------------------------------------

BASH_TOOL = ToolSpec(
    name="Bash",
    description="Executes a given bash command and returns its output.",
    input_schema={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The command to execute"},
            "description": {"type": "string", "description": "Description of what this command does"},
            "timeout": {"type": "number", "description": "Optional timeout in milliseconds"},
            "run_in_background": {"type": "boolean", "description": "Run in background"},
        },
        "required": ["command"],
    },
    required_permission="workspace-write",
)

READ_TOOL = ToolSpec(
    name="Read",
    description="Reads a file from the local filesystem.",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "offset": {"type": "number", "description": "Line number to start reading from"},
            "limit": {"type": "number", "description": "Number of lines to read"},
        },
        "required": ["file_path"],
    },
    required_permission="read-only",
)

WRITE_TOOL = ToolSpec(
    name="Write",
    description="Writes a file to the local filesystem.",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "content": {"type": "string", "description": "The content to write"},
        },
        "required": ["file_path", "content"],
    },
    required_permission="workspace-write",
)

EDIT_TOOL = ToolSpec(
    name="Edit",
    description="Performs exact string replacements in files.",
    input_schema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute path to the file"},
            "old_string": {"type": "string", "description": "The text to replace"},
            "new_string": {"type": "string", "description": "The replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences"},
        },
        "required": ["file_path", "old_string", "new_string"],
    },
    required_permission="workspace-write",
)

GLOB_TOOL = ToolSpec(
    name="Glob",
    description="Fast file pattern matching tool.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Glob pattern to match"},
            "path": {"type": "string", "description": "Directory to search in"},
        },
        "required": ["pattern"],
    },
    required_permission="read-only",
)

GREP_TOOL = ToolSpec(
    name="Grep",
    description="Search tool built on regex matching.",
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex pattern to search for"},
            "path": {"type": "string", "description": "File or directory to search"},
            "glob": {"type": "string", "description": "Glob pattern to filter files"},
            "output_mode": {
                "type": "string",
                "enum": ["content", "files_with_matches", "count"],
            },
            "-i": {"type": "boolean", "description": "Case insensitive search"},
            "-n": {"type": "boolean", "description": "Show line numbers"},
            "-A": {"type": "number", "description": "Lines after match"},
            "-B": {"type": "number", "description": "Lines before match"},
            "-C": {"type": "number", "description": "Context lines"},
            "head_limit": {"type": "number", "description": "Limit output entries"},
        },
        "required": ["pattern"],
    },
    required_permission="read-only",
)

WEB_SEARCH_TOOL = ToolSpec(
    name="WebSearch",
    description="Search the web for information.",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
        },
        "required": ["query"],
    },
    required_permission="read-only",
)

WEB_FETCH_TOOL = ToolSpec(
    name="WebFetch",
    description="Fetch content from a URL.",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "URL to fetch"},
        },
        "required": ["url"],
    },
    required_permission="read-only",
)

AGENT_TOOL = ToolSpec(
    name="Agent",
    description="Launch a sub-agent to handle complex tasks.",
    input_schema={
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "Task for the agent"},
            "description": {"type": "string", "description": "Short description"},
            "subagent_type": {"type": "string", "description": "Agent type"},
        },
        "required": ["prompt", "description"],
    },
    required_permission="read-only",
)

TODO_TOOL = ToolSpec(
    name="TodoWrite",
    description="Create and manage a structured task list.",
    input_schema={
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]},
                        "activeForm": {"type": "string"},
                    },
                    "required": ["content", "status", "activeForm"],
                },
            },
        },
        "required": ["todos"],
    },
    required_permission="read-only",
)


# ---------------------------------------------------------------------------
# Global tool registry
# ---------------------------------------------------------------------------

ALL_BUILTIN_TOOLS: list[ToolSpec] = [
    BASH_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    EDIT_TOOL,
    GLOB_TOOL,
    GREP_TOOL,
    WEB_SEARCH_TOOL,
    WEB_FETCH_TOOL,
    AGENT_TOOL,
    TODO_TOOL,
]


class GlobalToolRegistry:
    """Registry of all available tools.

    Maps to: rust/crates/tools/src/lib.rs::GlobalToolRegistry
    """

    def __init__(self) -> None:
        self._tools: dict[str, RuntimeToolDefinition] = {}
        # Register builtins
        for spec in ALL_BUILTIN_TOOLS:
            self._tools[spec.name] = RuntimeToolDefinition(spec=spec, source="builtin")

    def get(self, name: str) -> RuntimeToolDefinition | None:
        return self._tools.get(name)

    def register(self, definition: RuntimeToolDefinition) -> None:
        self._tools[definition.spec.name] = definition

    def all_tools(self) -> list[RuntimeToolDefinition]:
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())

    def to_api_tools(self) -> list[dict[str, Any]]:
        """Convert all tools to API tool definitions."""
        return [
            {
                "name": t.spec.name,
                "description": t.spec.description,
                "input_schema": t.spec.input_schema,
            }
            for t in self._tools.values()
        ]


# Module-level singleton
_registry: GlobalToolRegistry | None = None


def get_tool_registry() -> GlobalToolRegistry:
    """Get the global tool registry singleton."""
    global _registry
    if _registry is None:
        _registry = GlobalToolRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Tool executor implementation
# ---------------------------------------------------------------------------

class BuiltinToolExecutor:
    """Executes built-in tools (Bash, Read, Write, Edit, Glob, Grep).

    Implements the ToolExecutor protocol from conversation.py.
    """

    def __init__(self, cwd: str | None = None) -> None:
        self.cwd = cwd

    async def execute(self, tool_name: str, tool_input: str) -> str:
        """Execute a tool and return the result as a string."""
        try:
            params = json.loads(tool_input) if tool_input else {}
        except json.JSONDecodeError:
            params = {}

        match tool_name:
            case "Bash":
                return await self._exec_bash(params)
            case "Read":
                return self._exec_read(params)
            case "Write":
                return self._exec_write(params)
            case "Edit":
                return self._exec_edit(params)
            case "Glob":
                return self._exec_glob(params)
            case "Grep":
                return self._exec_grep(params)
            case _:
                return f"Tool '{tool_name}' is not yet implemented in the Python port."

    async def _exec_bash(self, params: dict[str, Any]) -> str:
        from pathlib import Path

        cmd_input = BashCommandInput(
            command=params.get("command", ""),
            timeout_ms=int(params.get("timeout", 120_000)),
            description=params.get("description", ""),
            run_in_background=params.get("run_in_background", False),
            cwd=Path(self.cwd) if self.cwd else None,
        )
        result = await execute_bash(cmd_input)

        output_parts = []
        if result.stdout:
            output_parts.append(result.stdout)
        if result.stderr:
            output_parts.append(f"STDERR:\n{result.stderr}")
        if result.exit_code is not None and result.exit_code != 0:
            output_parts.append(f"Exit code: {result.exit_code}")
        if result.timed_out:
            output_parts.append("(Command timed out)")

        return "\n".join(output_parts) if output_parts else "(no output)"

    @staticmethod
    def _exec_read(params: dict[str, Any]) -> str:
        result = read_file(
            file_path=params["file_path"],
            start_line=params.get("offset"),
            end_line=(
                params["offset"] + params["limit"]
                if params.get("offset") and params.get("limit")
                else params.get("limit")
            ),
        )
        return result.content

    @staticmethod
    def _exec_write(params: dict[str, Any]) -> str:
        result = write_file(
            file_path=params["file_path"],
            content=params["content"],
        )
        action = "Created" if result.created else "Updated"
        return f"{action} {result.file_path}"

    @staticmethod
    def _exec_edit(params: dict[str, Any]) -> str:
        result = edit_file(
            file_path=params["file_path"],
            old_string=params["old_string"],
            new_string=params["new_string"],
            replace_all=params.get("replace_all", False),
        )
        return f"Replaced {result.replacements} occurrence(s) in {result.file_path}"

    @staticmethod
    def _exec_glob(params: dict[str, Any]) -> str:
        result = glob_search(
            pattern=params["pattern"],
            path=params.get("path"),
        )
        if not result.filenames:
            return "No files found."
        lines = [f"Found {result.num_files} file(s) in {result.duration_ms:.0f}ms:"]
        for f in result.filenames:
            lines.append(f"  {f}")
        if result.truncated:
            lines.append("  ... (results truncated)")
        return "\n".join(lines)

    @staticmethod
    def _exec_grep(params: dict[str, Any]) -> str:
        result = grep_search(
            pattern=params["pattern"],
            path=params.get("path"),
            glob_filter=params.get("glob"),
            case_insensitive=params.get("-i", False),
        )
        if not result.matches:
            return "No matches found."
        lines = [f"Found {len(result.matches)} match(es) in {result.duration_ms:.0f}ms:"]
        for m in result.matches:
            lines.append(f"  {m.file}:{m.line_number}: {m.content}")
        if result.truncated:
            lines.append("  ... (results truncated)")
        return "\n".join(lines)
