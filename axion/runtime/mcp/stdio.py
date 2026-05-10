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

    async def connect(self) -> None:
        """Start the MCP server process and initialize."""
        import os

        env = {**os.environ, **(self.env or {})}
        self._process = await asyncio.create_subprocess_exec(
            self.command,
            *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        self._reader = self._process.stdout
        self._writer = self._process.stdin

        # Start reading responses
        self._read_task = asyncio.create_task(self._read_loop())

        # Initialize
        _init_result = await self._send_request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "axion-code", "version": "1.0.0"},
        })

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
        """Shutdown the MCP server."""
        if self._read_task:
            self._read_task.cancel()
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> JsonRpcResponse | None:
        req_id = self._next_id()
        request = JsonRpcRequest(method=method, params=params, id=req_id)

        future: asyncio.Future[JsonRpcResponse] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        await self._write_message(request.to_dict())

        try:
            return await asyncio.wait_for(future, timeout=30.0)
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
        content = json.dumps(data)
        message = f"Content-Length: {len(content)}\r\n\r\n{content}"
        self._writer.write(message.encode())
        await self._writer.drain()

    async def _read_loop(self) -> None:
        """Read JSON-RPC responses from the server."""
        if self._reader is None:
            return

        buffer = b""
        while True:
            try:
                chunk = await self._reader.read(4096)
                if not chunk:
                    break
                buffer += chunk

                # Parse Content-Length header
                while b"\r\n\r\n" in buffer:
                    header_end = buffer.index(b"\r\n\r\n")
                    header = buffer[:header_end].decode()
                    content_length = 0
                    for line in header.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            content_length = int(line.split(":")[1].strip())

                    body_start = header_end + 4
                    if len(buffer) < body_start + content_length:
                        break  # Not enough data yet

                    body = buffer[body_start:body_start + content_length].decode()
                    buffer = buffer[body_start + content_length:]

                    try:
                        data = json.loads(body)
                        response = JsonRpcResponse.from_dict(data)
                        if response.id is not None and response.id in self._pending:
                            future = self._pending.pop(response.id)
                            if not future.done():
                                future.set_result(response)
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON from MCP server")

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
