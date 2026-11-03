"""MCP (Model Context Protocol) server manager with JSON-RPC over stdio.

Maps to: rust/crates/runtime/src/mcp_stdio.rs
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


# ---------------------------------------------------------------------------
# JSON-RPC types
# ---------------------------------------------------------------------------

@dataclass
class JsonRpcRequest:
    method: str
    params: dict[str, Any] | None = None
    id: str | int | None = None
    jsonrpc: str = "2.0"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": self.jsonrpc, "method": self.method}
        if self.id is not None:
            d["id"] = self.id
        if self.params is not None:
            d["params"] = self.params
        return d


@dataclass
class JsonRpcError:
    code: int
    message: str
    data: Any = None


@dataclass
class JsonRpcResponse:
    id: str | int | None = None
    result: Any = None
    error: JsonRpcError | None = None
    jsonrpc: str = "2.0"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JsonRpcResponse:
        error = None
        if "error" in data:
            e = data["error"]
            error = JsonRpcError(code=e["code"], message=e["message"], data=e.get("data"))
        return cls(
            id=data.get("id"),
            result=data.get("result"),
            error=error,
        )


# ---------------------------------------------------------------------------
# MCP types
# ---------------------------------------------------------------------------

@dataclass
class McpTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpResource:
    uri: str
    name: str
    description: str = ""
    mime_type: str | None = None


@dataclass
class McpToolCallResult:
    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False


# ---------------------------------------------------------------------------
# MCP Server Connection
# ---------------------------------------------------------------------------

class McpServerConnection:
    """Manages a single MCP server connection over stdio."""

    def __init__(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env
        self._process: asyncio.subprocess.Process | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[JsonRpcResponse]] = {}
        self._tools: list[McpTool] = []
        self._resources: list[McpResource] = []
        self._read_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None

    async def connect(self) -> None:
        """Start the MCP server process and initialize."""
        import os
        import shutil
        import sys as _sys

        env = {**os.environ, **(self.env or {})}
        # Resolve the command for the platform. On Windows, launchers like `npx`/`npm` are `.cmd`
        # scripts that CreateProcess can't execute directly, so run them through the shell.
        exe = shutil.which(self.command) or self.command
        argv: list[str]
        if _sys.platform == "win32" and exe.lower().endswith((".cmd", ".bat")):
            comspec = os.environ.get("COMSPEC", "cmd.exe")
            argv = [comspec, "/c", exe, *self.args]
        else:
            argv = [exe, *self.args]
        self._process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            limit=10 * 1024 * 1024,  # allow large tool-list lines (default StreamReader limit is 64 KB)
        )
        self._reader = self._process.stdout
        self._writer = self._process.stdin

        # Start reading responses, and drain stderr so a chatty server can't fill the OS pipe buffer
        # (~64 KB) and deadlock.
        self._read_task = asyncio.create_task(self._read_loop())
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        # Initialize. First run can be slow (npx may download the server + a browser), so allow more time.
        _init_result = await self._send_request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "axion-code", "version": "1.0.1"},
        }, timeout=180.0)

        # Send initialized notification
        await self._send_notification("notifications/initialized", {})

        # List tools
        tools_result = await self._send_request("tools/list", {})
        if tools_result and tools_result.result:
            for t in tools_result.result.get("tools", []):
                self._tools.append(McpTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {}),
                ))

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpToolCallResult:
        """Call a tool on the MCP server."""
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result and result.error:
            return McpToolCallResult(
                content=[{"type": "text", "text": result.error.message}],
                is_error=True,
            )
        if result and result.result:
            return McpToolCallResult(
                content=result.result.get("content", []),
                is_error=result.result.get("isError", False),
            )
        return McpToolCallResult(is_error=True)

    @property
    def tools(self) -> list[McpTool]:
        return self._tools

    @property
    def resources(self) -> list[McpResource]:
        return self._resources

    async def disconnect(self) -> None:
        """Shutdown the MCP server, awaiting cancelled tasks and closing the writer (no leaks)."""
        for task in (self._read_task, getattr(self, "_stderr_task", None)):
            if task is not None:
                task.cancel()
                try:
                    await task
                except (asyncio.CancelledError, Exception):
                    pass
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                try:
                    self._process.kill()
                except ProcessLookupError:
                    pass

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_request(
        self, method: str, params: dict[str, Any], timeout: float = 30.0
    ) -> JsonRpcResponse | None:
        req_id = self._next_id()
        request = JsonRpcRequest(method=method, params=params, id=req_id)

        future: asyncio.Future[JsonRpcResponse] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        await self._write_message(request.to_dict())

        try:
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            logger.error("MCP request timed out: %s", method)
            return None

    async def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        request = JsonRpcRequest(method=method, params=params)
        await self._write_message(request.to_dict())

    async def _write_message(self, data: dict[str, Any]) -> None:
        if self._writer is None:
            return
        # MCP stdio transport is newline-delimited JSON-RPC (one JSON object per line), NOT the
        # LSP-style Content-Length framing this used before — which no real MCP server understands,
        # so initialize never completed and every server silently exposed zero tools.
        line = json.dumps(data) + "\n"
        self._writer.write(line.encode("utf-8"))
        await self._writer.drain()

    async def _drain_stderr(self) -> None:
        """Consume the server's stderr so its pipe buffer never fills and blocks the process."""
        stderr = self._process.stderr if self._process else None
        if stderr is None:
            return
        try:
            while True:
                line = await stderr.readline()
                if not line:
                    break
                logger.debug("MCP server stderr: %s", line.decode("utf-8", errors="replace").rstrip())
        except (asyncio.CancelledError, Exception):
            return

    async def _read_loop(self) -> None:
        """Read newline-delimited JSON-RPC responses from the server."""
        if self._reader is None:
            return
        while True:
            try:
                raw = await self._reader.readline()
                if not raw:
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    data = json.loads(raw)
                    response = JsonRpcResponse.from_dict(data)
                    if response.id is not None and response.id in self._pending:
                        future = self._pending.pop(response.id)
                        if not future.done():
                            future.set_result(response)
                except json.JSONDecodeError:
                    logger.warning("Invalid JSON line from MCP server: %s", raw[:200])
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MCP read error: %s", exc)
                break


# ---------------------------------------------------------------------------
# MCP Server Manager
# ---------------------------------------------------------------------------

class McpServerManager:
    """Manages multiple MCP server connections.

    Maps to: rust/crates/runtime/src/mcp_stdio.rs::McpServerManager
    """

    def __init__(self) -> None:
        self._servers: dict[str, McpServerConnection] = {}

    async def connect(
        self,
        name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> McpServerConnection:
        """Connect to an MCP server."""
        conn = McpServerConnection(name=name, command=command, args=args, env=env)
        await conn.connect()
        self._servers[name] = conn
        return conn

    def get(self, name: str) -> McpServerConnection | None:
        return self._servers.get(name)

    def all_servers(self) -> list[McpServerConnection]:
        return list(self._servers.values())

    def all_tools(self) -> list[tuple[str, McpTool]]:
        """Get all tools from all connected servers."""
        tools = []
        for server in self._servers.values():
            for tool in server.tools:
                tools.append((server.name, tool))
        return tools

    async def disconnect_all(self) -> None:
        """Disconnect all servers."""
        for server in self._servers.values():
            await server.disconnect()
        self._servers.clear()
