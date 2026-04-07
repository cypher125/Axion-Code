"""LSP (Language Server Protocol) client with JSON-RPC communication.

Maps to: rust/crates/runtime/src/lsp_client.rs
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class LspAction(enum.Enum):
    DIAGNOSTICS = "diagnostics"
    HOVER = "hover"
    DEFINITION = "definition"
    REFERENCES = "references"
    COMPLETION = "completion"
    SYMBOLS = "symbols"
    FORMAT = "format"


class LspServerStatus(enum.Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    STARTING = "starting"
    ERROR = "error"


class LspSeverity(enum.Enum):
    ERROR = "error"
    WARNING = "warning"
    INFORMATION = "information"
    HINT = "hint"


@dataclass
class LspDiagnostic:
    path: str
    line: int
    character: int
    severity: LspSeverity
    message: str
    source: str = ""
    code: str | None = None
    end_line: int | None = None
    end_character: int | None = None


@dataclass
class LspLocation:
    path: str
    line: int
    character: int
    end_line: int | None = None
    end_character: int | None = None
    preview: str = ""


@dataclass
class LspHoverResult:
    content: str
    language: str = ""
    range_start_line: int | None = None
    range_start_character: int | None = None


@dataclass
class LspCompletionItem:
    label: str
    kind: str = ""
    detail: str = ""
    insert_text: str = ""
    sort_text: str = ""


@dataclass
class LspSymbol:
    name: str
    kind: str
    path: str
    line: int
    character: int
    container_name: str = ""


@dataclass
class LspServerInfo:
    """Information about a connected LSP server."""

    language: str
    command: str = ""
    status: LspServerStatus = LspServerStatus.DISCONNECTED
    capabilities: dict[str, Any] = field(default_factory=dict)
    root_uri: str = ""
    error_message: str = ""


# ---------------------------------------------------------------------------
# LSP JSON-RPC client
# ---------------------------------------------------------------------------

class LspClient:
    """JSON-RPC client for a single LSP server process.

    Communicates via stdin/stdout using Content-Length headers.
    """

    def __init__(self, language: str, command: str, args: list[str] | None = None) -> None:
        self.language = language
        self.command = command
        self.args = args or []
        self._process: asyncio.subprocess.Process | None = None
        self._request_id = 0
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._read_task: asyncio.Task[None] | None = None
        self._capabilities: dict[str, Any] = {}

    async def start(self, root_uri: str = "") -> bool:
        """Start the LSP server process and initialize."""
        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command, *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as exc:
            logger.error("Failed to start LSP server %s: %s", self.command, exc)
            return False

        self._read_task = asyncio.create_task(self._read_loop())

        # Send initialize request
        result = await self._request("initialize", {
            "processId": None,
            "rootUri": root_uri,
            "capabilities": {
                "textDocument": {
                    "completion": {"completionItem": {"snippetSupport": False}},
                    "hover": {"contentFormat": ["plaintext"]},
                    "definition": {},
                    "references": {},
                    "documentSymbol": {},
                    "formatting": {},
                    "publishDiagnostics": {},
                },
            },
        })

        if result:
            self._capabilities = result.get("capabilities", {})

        # Send initialized notification
        await self._notify("initialized", {})
        return True

    async def get_diagnostics(self, uri: str) -> list[LspDiagnostic]:
        """Get diagnostics for a document. Note: LSP pushes diagnostics, this is a placeholder."""
        return []

    async def hover(self, uri: str, line: int, character: int) -> LspHoverResult | None:
        """Get hover information at a position."""
        result = await self._request("textDocument/hover", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if not result or "contents" not in result:
            return None

        contents = result["contents"]
        if isinstance(contents, str):
            return LspHoverResult(content=contents)
        if isinstance(contents, dict):
            return LspHoverResult(
                content=contents.get("value", ""),
                language=contents.get("language", ""),
            )
        return None

    async def definition(self, uri: str, line: int, character: int) -> list[LspLocation]:
        """Go to definition."""
        result = await self._request("textDocument/definition", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        return self._parse_locations(result)

    async def references(self, uri: str, line: int, character: int) -> list[LspLocation]:
        """Find all references."""
        result = await self._request("textDocument/references", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
            "context": {"includeDeclaration": True},
        })
        return self._parse_locations(result)

    async def completion(self, uri: str, line: int, character: int) -> list[LspCompletionItem]:
        """Get completions at a position."""
        result = await self._request("textDocument/completion", {
            "textDocument": {"uri": uri},
            "position": {"line": line, "character": character},
        })
        if not result:
            return []

        items = result.get("items", []) if isinstance(result, dict) else result
        completions = []
        for item in items[:50]:  # Limit
            completions.append(LspCompletionItem(
                label=item.get("label", ""),
                kind=str(item.get("kind", "")),
                detail=item.get("detail", ""),
                insert_text=item.get("insertText", item.get("label", "")),
                sort_text=item.get("sortText", ""),
            ))
        return completions

    async def document_symbols(self, uri: str) -> list[LspSymbol]:
        """Get symbols in a document."""
        result = await self._request("textDocument/documentSymbol", {
            "textDocument": {"uri": uri},
        })
        if not result:
            return []

        symbols = []
        for sym in result:
            location = sym.get("location", {})
            range_ = location.get("range", sym.get("range", {}))
            start = range_.get("start", {})
            symbols.append(LspSymbol(
                name=sym.get("name", ""),
                kind=str(sym.get("kind", "")),
                path=location.get("uri", uri),
                line=start.get("line", 0),
                character=start.get("character", 0),
                container_name=sym.get("containerName", ""),
            ))
        return symbols

    async def shutdown(self) -> None:
        """Shutdown the LSP server."""
        if self._process:
            await self._request("shutdown", None)
            await self._notify("exit", None)
            if self._read_task:
                self._read_task.cancel()
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except (asyncio.TimeoutError, ProcessLookupError):
                self._process.kill()

    @staticmethod
    def _parse_locations(result: Any) -> list[LspLocation]:
        if not result:
            return []
        locs = result if isinstance(result, list) else [result]
        locations = []
        for loc in locs:
            uri = loc.get("uri", "")
            range_ = loc.get("range", {})
            start = range_.get("start", {})
            end = range_.get("end", {})
            locations.append(LspLocation(
                path=uri,
                line=start.get("line", 0),
                character=start.get("character", 0),
                end_line=end.get("line"),
                end_character=end.get("character"),
            ))
        return locations

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def _request(self, method: str, params: Any) -> Any:
        if not self._process or not self._process.stdin:
            return None
        req_id = self._next_id()
        msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}

        future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending[req_id] = future

        await self._write(msg)

        try:
            response = await asyncio.wait_for(future, timeout=10.0)
            return response.get("result")
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            return None

    async def _notify(self, method: str, params: Any) -> None:
        if not self._process or not self._process.stdin:
            return
        msg: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        await self._write(msg)

    async def _write(self, msg: dict[str, Any]) -> None:
        assert self._process and self._process.stdin
        content = json.dumps(msg)
        header = f"Content-Length: {len(content)}\r\n\r\n"
        self._process.stdin.write((header + content).encode())
        await self._process.stdin.drain()

    async def _read_loop(self) -> None:
        assert self._process and self._process.stdout
        buffer = b""
        while True:
            try:
                chunk = await self._process.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk

                while b"\r\n\r\n" in buffer:
                    header_end = buffer.index(b"\r\n\r\n")
                    header = buffer[:header_end].decode()
                    content_length = 0
                    for line in header.split("\r\n"):
                        if line.lower().startswith("content-length:"):
                            content_length = int(line.split(":")[1].strip())

                    body_start = header_end + 4
                    if len(buffer) < body_start + content_length:
                        break

                    body = buffer[body_start:body_start + content_length].decode()
                    buffer = buffer[body_start + content_length:]

                    try:
                        data = json.loads(body)
                        msg_id = data.get("id")
                        if msg_id is not None and msg_id in self._pending:
                            future = self._pending.pop(msg_id)
                            if not future.done():
                                future.set_result(data)
                    except json.JSONDecodeError:
                        pass
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("LSP read error: %s", exc)
                break


# ---------------------------------------------------------------------------
# LSP Registry
# ---------------------------------------------------------------------------

class LspRegistry:
    """Registry of connected LSP servers.

    Maps to: rust/crates/runtime/src/lsp_client.rs::LspRegistry
    """

    def __init__(self) -> None:
        self._clients: dict[str, LspClient] = {}
        self._server_info: dict[str, LspServerInfo] = {}
        self._diagnostics: list[LspDiagnostic] = []

    async def connect(
        self, language: str, command: str, args: list[str] | None = None, root_uri: str = "",
    ) -> bool:
        """Start and connect to an LSP server."""
        client = LspClient(language=language, command=command, args=args)
        success = await client.start(root_uri=root_uri)

        info = LspServerInfo(
            language=language,
            command=command,
            status=LspServerStatus.CONNECTED if success else LspServerStatus.ERROR,
            root_uri=root_uri,
        )
        self._server_info[language] = info

        if success:
            self._clients[language] = client
        return success

    def get_client(self, language: str) -> LspClient | None:
        return self._clients.get(language)

    def get_status(self, language: str) -> LspServerStatus:
        info = self._server_info.get(language)
        return info.status if info else LspServerStatus.DISCONNECTED

    def all_servers(self) -> dict[str, LspServerInfo]:
        return dict(self._server_info)

    def connected_languages(self) -> list[str]:
        return [lang for lang, info in self._server_info.items()
                if info.status == LspServerStatus.CONNECTED]

    def add_diagnostics(self, diagnostics: list[LspDiagnostic]) -> None:
        self._diagnostics.extend(diagnostics)

    def get_diagnostics(self, path: str | None = None) -> list[LspDiagnostic]:
        if path is None:
            return list(self._diagnostics)
        return [d for d in self._diagnostics if d.path == path]

    def clear_diagnostics(self, path: str | None = None) -> None:
        if path is None:
            self._diagnostics.clear()
        else:
            self._diagnostics = [d for d in self._diagnostics if d.path != path]

    async def shutdown_all(self) -> None:
        for client in self._clients.values():
            await client.shutdown()
        self._clients.clear()
        for info in self._server_info.values():
            info.status = LspServerStatus.DISCONNECTED
