"""Global tool registry and tool definitions.

Maps to: rust/crates/tools/src/lib.rs
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any

from axion.runtime.bash import BashCommandInput, execute_bash
from axion.runtime.file_ops import (
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

    def __init__(
        self,
        cwd: str | None = None,
        hook_runner: Any | None = None,
    ) -> None:
        self.cwd = cwd
        self.hook_runner = hook_runner  # Optional HookRunner instance

    async def execute(self, tool_name: str, tool_input: str) -> str:
        """Execute a tool and return the result as a string.

        If a hook_runner is attached, pre/post tool-use hooks are invoked
        around the actual tool execution.
        """
        # --- Pre-tool-use hook ---
        if self.hook_runner is not None:
            pre_result = await self.hook_runner.run_pre_tool_use(tool_name, tool_input)
            if pre_result.denied:
                deny_msg = "; ".join(pre_result.messages) or "Denied by pre-tool-use hook"
                return f"Hook denied: {deny_msg}"

        try:
            params = json.loads(tool_input) if tool_input else {}
        except json.JSONDecodeError:
            params = {}

        _is_error = False
        try:
            result = await self._dispatch(tool_name, params)
        except Exception as exc:
            _is_error = True
            result = f"Tool error: {exc}"
            # --- Post-tool-use failure hook ---
            if self.hook_runner is not None:
                fail_result = await self.hook_runner.run_post_tool_use_failure(
                    tool_name, tool_input, str(exc)
                )
                if fail_result.messages:
                    result += "\n" + "\n".join(f"[hook] {m}" for m in fail_result.messages)
            return result

        # --- Post-tool-use hook ---
        if self.hook_runner is not None:
            post_result = await self.hook_runner.run_post_tool_use(
                tool_name, tool_input, result, is_error=False
            )
            if post_result.denied:
                deny_msg = "; ".join(post_result.messages) or "Denied by post-tool-use hook"
                return f"Post-hook error: {deny_msg}\nOriginal output: {result}"

        return result

    async def _dispatch(self, tool_name: str, params: dict[str, Any]) -> str:
        """Dispatch to the appropriate tool handler."""
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
            case "WebFetch":
                return await self._exec_web_fetch(params)
            case "WebSearch":
                return await self._exec_web_search(params)
            case "TodoWrite":
                return self._exec_todo_write(params)
            case "Agent":
                return await self._exec_agent(params)
            case "NotebookEdit":
                return self._exec_notebook_edit(params)
            case "Skill":
                return self._exec_skill(params)
            case "ToolSearch":
                return self._exec_tool_search(params)
            case _:
                return f"Tool '{tool_name}' is not yet implemented."

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

    # -----------------------------------------------------------------------
    # WebFetch — actually fetches URLs using httpx
    # -----------------------------------------------------------------------

    @staticmethod
    async def _exec_web_fetch(params: dict[str, Any]) -> str:
        """Fetch content from a URL."""
        import httpx

        url = params.get("url", "")
        if not url:
            return "Error: url parameter is required"

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Axion-Code/0.1.0"},
            ) as client:
                response = await client.get(url)
                content_type = response.headers.get("content-type", "")

                if response.status_code != 200:
                    return f"HTTP {response.status_code}: {response.reason_phrase}"

                # Handle text content
                if "text/" in content_type or "json" in content_type or "xml" in content_type:
                    text = response.text
                    # Truncate very long responses
                    if len(text) > 50_000:
                        text = text[:50_000] + "\n\n[Content truncated at 50,000 characters]"
                    return text

                # Binary content — return metadata
                size = len(response.content)
                return (
                    f"Binary content ({content_type}), {size:,} bytes.\n"
                    f"Cannot display binary content as text."
                )

        except httpx.TimeoutException:
            return f"Error: Request to {url} timed out after 30 seconds"
        except httpx.HTTPError as exc:
            return f"Error fetching {url}: {exc}"

    # -----------------------------------------------------------------------
    # WebSearch — uses DuckDuckGo HTML search (no API key needed)
    # -----------------------------------------------------------------------

    @staticmethod
    async def _exec_web_search(params: dict[str, Any]) -> str:
        """Search the web using DuckDuckGo."""
        import re

        import httpx

        query = params.get("query", "")
        if not query:
            return "Error: query parameter is required"

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={
                    "User-Agent": "Mozilla/5.0 (compatible; Axion-Code/0.1.0)",
                },
            ) as client:
                # Use DuckDuckGo HTML lite (no API key required)
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                )

                if response.status_code != 200:
                    return f"Search failed: HTTP {response.status_code}"

                html = response.text

                # Extract results from DuckDuckGo HTML
                results: list[str] = []

                # Find result blocks
                result_pattern = re.compile(
                    r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
                    r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
                    re.DOTALL,
                )

                for match in result_pattern.finditer(html):
                    url = match.group(1)
                    title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
                    snippet = re.sub(r"<[^>]+>", "", match.group(3)).strip()

                    if title and url:
                        results.append(f"**{title}**\n  {url}\n  {snippet}\n")

                    if len(results) >= 10:
                        break

                # Fallback: try simpler pattern
                if not results:
                    link_pattern = re.compile(
                        r'<a[^>]*class="result__a"[^>]*>(.*?)</a>', re.DOTALL
                    )
                    for match in link_pattern.finditer(html):
                        title = re.sub(r"<[^>]+>", "", match.group(1)).strip()
                        if title:
                            results.append(f"- {title}")
                        if len(results) >= 10:
                            break

                if not results:
                    return f"No results found for: {query}"

                header = f"Search results for: {query}\n\n"
                return header + "\n".join(results)

        except httpx.TimeoutException:
            return "Error: Search request timed out"
        except httpx.HTTPError as exc:
            return f"Error performing search: {exc}"

    # -----------------------------------------------------------------------
    # TodoWrite — manages a task list
    # -----------------------------------------------------------------------

    _todo_list: list[dict[str, str]] = []

    @classmethod
    def _exec_todo_write(cls, params: dict[str, Any]) -> str:
        """Create and manage a structured task list."""
        todos = params.get("todos", [])
        if not todos:
            return "No todos provided."

        cls._todo_list = []
        for todo in todos:
            cls._todo_list.append({
                "content": todo.get("content", ""),
                "status": todo.get("status", "pending"),
                "activeForm": todo.get("activeForm", ""),
            })

        # Format output
        lines = ["Task list updated:", ""]
        for i, todo in enumerate(cls._todo_list, 1):
            status = todo["status"]
            icon = {"pending": "○", "in_progress": "◉", "completed": "✓"}.get(status, "?")
            lines.append(f"  {icon} {i}. [{status}] {todo['content']}")

        return "\n".join(lines)

    @classmethod
    def get_todo_list(cls) -> list[dict[str, str]]:
        """Get the current todo list."""
        return list(cls._todo_list)

    # -----------------------------------------------------------------------
    # Agent — spawns a sub-agent as a subprocess
    # -----------------------------------------------------------------------

    async def _exec_agent(self, params: dict[str, Any]) -> str:
        """Launch a sub-agent to handle complex tasks.

        Spawns a new axion process with the agent's prompt, runs it, and returns
        the result. This provides context isolation — the sub-agent gets a fresh
        conversation.
        """
        import asyncio
        import sys

        prompt_text = params.get("prompt", "")
        description = params.get("description", "agent task")
        model = params.get("model")

        if not prompt_text:
            return "Error: prompt parameter is required"

        # Build the sub-agent command
        cmd = [sys.executable, "-m", "axion.cli.main", "-p", prompt_text]
        if model:
            cmd.extend(["-m", model])
        cmd.extend(["--output-format", "json"])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.cwd,
                env={**os.environ},
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=300.0,  # 5 min timeout
            )

            output = stdout.decode("utf-8", errors="replace")

            # Try to parse JSON output and extract the message
            try:
                data = json.loads(output)
                return data.get("message", output)
            except json.JSONDecodeError:
                return output if output.strip() else f"Agent completed with no output. stderr: {stderr.decode()[:500]}"

        except asyncio.TimeoutError:
            return f"Agent timed out after 300 seconds. Task: {description}"
        except Exception as exc:
            return f"Agent execution failed: {exc}"

    # -----------------------------------------------------------------------
    # NotebookEdit — edits Jupyter notebook cells
    # -----------------------------------------------------------------------

    @staticmethod
    def _exec_notebook_edit(params: dict[str, Any]) -> str:
        """Edit a Jupyter notebook cell."""
        notebook_path = params.get("notebook_path", "")
        cell_index = params.get("cell_index")
        new_source = params.get("new_source", "")
        cell_type = params.get("cell_type", "code")
        operation = params.get("operation", "replace")  # replace, insert, delete

        if not notebook_path:
            return "Error: notebook_path is required"

        from pathlib import Path

        path = Path(notebook_path)
        if not path.exists():
            return f"Error: Notebook not found: {notebook_path}"

        try:
            nb_data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            return f"Error reading notebook: {exc}"

        cells = nb_data.get("cells", [])

        if operation == "replace" and cell_index is not None:
            if cell_index < 0 or cell_index >= len(cells):
                return f"Error: cell_index {cell_index} out of range (0-{len(cells) - 1})"
            cells[cell_index]["source"] = new_source.splitlines(keepends=True)
            if cell_type:
                cells[cell_index]["cell_type"] = cell_type

        elif operation == "insert":
            insert_at = cell_index if cell_index is not None else len(cells)
            new_cell = {
                "cell_type": cell_type,
                "source": new_source.splitlines(keepends=True),
                "metadata": {},
            }
            if cell_type == "code":
                new_cell["outputs"] = []
                new_cell["execution_count"] = None
            cells.insert(insert_at, new_cell)

        elif operation == "delete" and cell_index is not None:
            if cell_index < 0 or cell_index >= len(cells):
                return f"Error: cell_index {cell_index} out of range"
            cells.pop(cell_index)

        else:
            return f"Error: unsupported operation '{operation}'"

        nb_data["cells"] = cells
        path.write_text(json.dumps(nb_data, indent=1, ensure_ascii=False), encoding="utf-8")

        return f"Notebook {operation}d cell at index {cell_index} in {notebook_path}"

    # -----------------------------------------------------------------------
    # Skill — loads and executes skill definitions
    # -----------------------------------------------------------------------

    def _exec_skill(self, params: dict[str, Any]) -> str:
        """Load and execute a skill by name or path."""
        from pathlib import Path

        from axion.runtime.skills import execute_skill, load_skill, resolve_skill

        skill_name = params.get("skill", params.get("name", ""))
        user_args = params.get("args", "")

        if not skill_name:
            return "Error: skill name is required"

        # Try to resolve by name from conventional directories
        cwd = Path(self.cwd) if self.cwd else Path.cwd()
        skill_path = resolve_skill(skill_name, cwd)

        # Fallback: treat as direct path
        if skill_path is None:
            candidate = Path(skill_name)
            if candidate.is_file():
                skill_path = candidate

        if skill_path is None:
            return f"Error: skill '{skill_name}' not found"

        try:
            skill = load_skill(skill_path)
        except Exception as exc:
            return f"Error loading skill '{skill_name}': {exc}"

        return execute_skill(skill, user_args)

    # -----------------------------------------------------------------------
    # ToolSearch — deferred tool schema loading
    # -----------------------------------------------------------------------

    @staticmethod
    def _exec_tool_search(params: dict[str, Any]) -> str:
        """Search for tools by keyword or fetch schemas by name."""
        from axion.tools.tool_search import tool_search

        query = params.get("query", "")
        max_results = int(params.get("max_results", 5))

        if not query:
            return "Error: query parameter is required"

        output = tool_search(query, max_results=max_results)

        # Format results
        if output.schemas:
            # Direct selection — return full schemas
            import json
            lines = [output.message, ""]
            for schema in output.schemas:
                lines.append(f"## {schema['name']}")
                lines.append(f"Description: {schema['description'][:200]}")
                lines.append(f"Schema: {json.dumps(schema['input_schema'], indent=2)}")
                lines.append("")
            return "\n".join(lines)

        if output.results:
            lines = [output.message, ""]
            for r in output.results:
                lines.append(f"  - **{r.name}** (score: {r.score:.1f}): {r.description}")
            lines.append("")
            lines.append("Use 'select:ToolName' to fetch the full schema.")
            return "\n".join(lines)

        return f"No tools found matching: {query}"
