"""Configuration management with 3-layer merge and full MCP server config.

Maps to: rust/crates/runtime/src/config.rs
"""

from __future__ import annotations

import enum
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ConfigSource(enum.Enum):
    USER = "user"
    PROJECT = "project"
    LOCAL = "local"
    ENVIRONMENT = "environment"


class ConfigError(Exception):
    """Configuration loading error."""


@dataclass
class ConfigEntry:
    """A single loaded configuration entry."""

    source: ConfigSource
    path: Path
    data: dict[str, Any]


# ---------------------------------------------------------------------------
# MCP server configuration (6 transport types)
# ---------------------------------------------------------------------------

@dataclass
class McpStdioServerConfig:
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    tool_call_timeout_ms: int | None = None


@dataclass
class McpRemoteServerConfig:
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    headers_helper: str | None = None
    auth: str | None = None  # "oauth" or None


@dataclass
class McpWebSocketServerConfig:
    url: str
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class McpSdkServerConfig:
    name: str


@dataclass
class McpManagedProxyServerConfig:
    url: str
    id: str


McpServerConfig = (
    McpStdioServerConfig
    | McpRemoteServerConfig
    | McpWebSocketServerConfig
    | McpSdkServerConfig
    | McpManagedProxyServerConfig
)


def parse_mcp_server_config(name: str, data: dict[str, Any]) -> McpServerConfig | None:
    """Parse a single MCP server config from JSON."""
    server_type = data.get("type", "stdio")

    if server_type == "stdio":
        return McpStdioServerConfig(
            command=data.get("command", ""),
            args=data.get("args", []),
            env=data.get("env", {}),
            tool_call_timeout_ms=data.get("toolCallTimeoutMs"),
        )
    if server_type in ("sse", "http"):
        return McpRemoteServerConfig(
            url=data.get("url", ""),
            headers=data.get("headers", {}),
            headers_helper=data.get("headersHelper"),
            auth=data.get("auth"),
        )
    if server_type == "ws":
        return McpWebSocketServerConfig(
            url=data.get("url", ""),
            headers=data.get("headers", {}),
        )
    if server_type == "sdk":
        return McpSdkServerConfig(name=data.get("name", name))
    if server_type == "managed_proxy":
        return McpManagedProxyServerConfig(
            url=data.get("url", ""),
            id=data.get("id", ""),
        )
    return None


# ---------------------------------------------------------------------------
# OAuth configuration
# ---------------------------------------------------------------------------

@dataclass
class OAuthConfig:
    client_id: str = ""
    authorize_url: str = ""
    token_url: str = ""
    callback_port: int = 4545
    scopes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Hook configuration
# ---------------------------------------------------------------------------

@dataclass
class HookMatcher:
    """Matches specific tools for hook execution."""

    tool_name: str | None = None
    tool_prefix: str | None = None

    def matches(self, tool_name: str) -> bool:
        if self.tool_name and self.tool_name == tool_name:
            return True
        if self.tool_prefix and tool_name.startswith(self.tool_prefix):
            return True
        if self.tool_name is None and self.tool_prefix is None:
            return True  # Match all
        return False


@dataclass
class HookEntry:
    """A single hook configuration entry."""

    command: str
    timeout_ms: int = 10_000
    matchers: list[HookMatcher] = field(default_factory=list)

    def matches_tool(self, tool_name: str) -> bool:
        if not self.matchers:
            return True
        return any(m.matches(tool_name) for m in self.matchers)


@dataclass
class RuntimeHookConfig:
    pre_tool_use: list[HookEntry] = field(default_factory=list)
    post_tool_use: list[HookEntry] = field(default_factory=list)
    post_tool_use_failure: list[HookEntry] = field(default_factory=list)


def parse_hook_entries(data: list[Any]) -> list[HookEntry]:
    """Parse hook entries from config."""
    entries: list[HookEntry] = []
    for item in data:
        if isinstance(item, str):
            entries.append(HookEntry(command=item))
        elif isinstance(item, dict):
            matchers = []
            for m in item.get("matchers", []):
                matchers.append(HookMatcher(
                    tool_name=m.get("tool_name"),
                    tool_prefix=m.get("tool_prefix"),
                ))
            entries.append(HookEntry(
                command=item.get("command", ""),
                timeout_ms=item.get("timeout_ms", 10_000),
                matchers=matchers,
            ))
    return entries


# ---------------------------------------------------------------------------
# Feature configuration
# ---------------------------------------------------------------------------

@dataclass
class RuntimeFeatureConfig:
    """Feature configuration extracted from merged config."""

    hooks: RuntimeHookConfig = field(default_factory=RuntimeHookConfig)
    plugins: dict[str, Any] = field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)
    oauth: OAuthConfig | None = None
    model: str | None = None
    permission_mode: str | None = None
    allowed_tools: list[str] | None = None
    denied_tools: list[str] | None = None


@dataclass
class RuntimeConfig:
    """Fully resolved configuration from all sources."""

    merged: dict[str, Any] = field(default_factory=dict)
    loaded_entries: list[ConfigEntry] = field(default_factory=list)
    feature_config: RuntimeFeatureConfig = field(default_factory=RuntimeFeatureConfig)


# ---------------------------------------------------------------------------
# Config loader
# ---------------------------------------------------------------------------

class ConfigLoader:
    """Loads and merges configuration from user, project, and local sources.

    Maps to: rust/crates/runtime/src/config.rs::ConfigLoader

    Resolution order (later overrides earlier):
      1. User: ~/.axion/settings.json, ~/.config/axion/settings.json, ~/.claude/settings.json
      2. Project: .axion.json, .claude.json
      3. Local: .axion/settings.json, .claude/settings.json
      4. Local: .axion/settings.local.json, .claude/settings.local.json
      5. Environment variables
    """

    def __init__(self, project_dir: Path | None = None) -> None:
        self.project_dir = project_dir or Path.cwd()

    def load(self) -> RuntimeConfig:
        """Load and merge all configuration sources."""
        entries: list[ConfigEntry] = []
        merged: dict[str, Any] = {}

        # 1. User config
        for user_path in self._user_config_paths():
            data = self._load_json(user_path)
            if data is not None:
                entries.append(ConfigEntry(source=ConfigSource.USER, path=user_path, data=data))
                self._deep_merge(merged, data)

        # 2. Project config (.axion.json first, .claude.json fallback)
        for proj_path in [
            self.project_dir / ".axion.json",
            self.project_dir / ".claude.json",
        ]:
            data = self._load_json(proj_path)
            if data is not None:
                entries.append(ConfigEntry(source=ConfigSource.PROJECT, path=proj_path, data=data))
                self._deep_merge(merged, data)

        # 3-4. Local config (.axion/ first, .claude/ fallback)
        for local_path in [
            self.project_dir / ".axion" / "settings.json",
            self.project_dir / ".axion" / "settings.local.json",
            self.project_dir / ".claude" / "settings.json",
            self.project_dir / ".claude" / "settings.local.json",
        ]:
            data = self._load_json(local_path)
            if data is not None:
                entries.append(ConfigEntry(source=ConfigSource.LOCAL, path=local_path, data=data))
                self._deep_merge(merged, data)

        # 5. Environment overrides
        env_model = os.environ.get("AXION_MODEL") or os.environ.get("CLAUDE_MODEL")

        # Build feature config
        feature = self._extract_features(merged)
        if env_model:
            feature.model = env_model

        return RuntimeConfig(merged=merged, loaded_entries=entries, feature_config=feature)

    @classmethod
    def default_for(cls, cwd: Path) -> ConfigLoader:
        """Create a loader for the given working directory."""
        return cls(project_dir=cwd)

    def _extract_features(self, merged: dict[str, Any]) -> RuntimeFeatureConfig:
        """Extract feature configuration from merged config."""
        feature = RuntimeFeatureConfig()

        # Permissions
        perms = merged.get("permissions", {})
        feature.permission_mode = perms.get("defaultMode")
        feature.allowed_tools = perms.get("allowedTools")
        feature.denied_tools = perms.get("deniedTools")

        # Model
        feature.model = merged.get("model")

        # Hooks
        hooks_data = merged.get("hooks", {})
        if hooks_data:
            feature.hooks = RuntimeHookConfig(
                pre_tool_use=parse_hook_entries(hooks_data.get("preToolUse", [])),
                post_tool_use=parse_hook_entries(hooks_data.get("postToolUse", [])),
                post_tool_use_failure=parse_hook_entries(
                    hooks_data.get("postToolUseFailure", [])
                ),
            )

        # MCP servers (full parsing)
        mcp_data = merged.get("mcpServers", {})
        for name, server_data in mcp_data.items():
            if isinstance(server_data, dict):
                config = parse_mcp_server_config(name, server_data)
                if config:
                    feature.mcp_servers[name] = config

        # OAuth
        oauth_data = merged.get("oauth", {})
        if oauth_data:
            feature.oauth = OAuthConfig(
                client_id=oauth_data.get("clientId", ""),
                authorize_url=oauth_data.get("authorizeUrl", ""),
                token_url=oauth_data.get("tokenUrl", ""),
                callback_port=oauth_data.get("callbackPort", 4545),
                scopes=oauth_data.get("scopes", []),
            )

        # Plugins
        feature.plugins = merged.get("plugins", {})

        return feature

    @staticmethod
    def _user_config_paths() -> list[Path]:
        home = Path.home()
        paths = [
            home / ".axion" / "settings.json",
            home / ".config" / "axion" / "settings.json",
            home / ".claude" / "settings.json",  # backwards compat
        ]
        # Check CLAUDE_CONFIG_DIR env
        config_dir = os.environ.get("CLAUDE_CONFIG_DIR")
        if config_dir:
            paths.insert(0, Path(config_dir) / "settings.json")
        return paths

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            text = path.read_text(encoding="utf-8")
            data = json.loads(text)
            return data if isinstance(data, dict) else None
        except (json.JSONDecodeError, OSError):
            return None

    @staticmethod
    def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigLoader._deep_merge(base[key], value)
            else:
                base[key] = value

    def render_config_report(self) -> str:
        """Render a human-readable configuration report."""
        config = self.load()
        lines = ["Configuration:"]
        for entry in config.loaded_entries:
            lines.append(f"  [{entry.source.value}] {entry.path}")

        fc = config.feature_config
        lines.append(f"\n  Model: {fc.model or '(default)'}")
        lines.append(f"  Permission mode: {fc.permission_mode or '(default)'}")

        if fc.mcp_servers:
            lines.append(f"\n  MCP servers ({len(fc.mcp_servers)}):")
            for name, srv in fc.mcp_servers.items():
                if isinstance(srv, McpStdioServerConfig):
                    lines.append(f"    {name}: stdio → {srv.command}")
                elif isinstance(srv, McpRemoteServerConfig):
                    lines.append(f"    {name}: remote → {srv.url}")
                else:
                    lines.append(f"    {name}: {type(srv).__name__}")

        if fc.hooks.pre_tool_use or fc.hooks.post_tool_use:
            hook_count = (
                len(fc.hooks.pre_tool_use)
                + len(fc.hooks.post_tool_use)
                + len(fc.hooks.post_tool_use_failure)
            )
            lines.append(f"\n  Hooks: {hook_count} configured")

        return "\n".join(lines)
