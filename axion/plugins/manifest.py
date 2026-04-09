"""Plugin manifest and metadata with full validation.

Maps to: rust/crates/plugins/src/lib.rs (manifest types + validation)
"""

from __future__ import annotations

import enum
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class PluginKind(enum.Enum):
    BUILTIN = "builtin"
    BUNDLED = "bundled"
    EXTERNAL = "external"


class PluginPermission(enum.Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"


class PluginToolPermission(enum.Enum):
    READ_ONLY = "read-only"
    WORKSPACE_WRITE = "workspace-write"
    DANGER_FULL_ACCESS = "danger-full-access"


@dataclass
class PluginMetadata:
    """Plugin identity and metadata."""

    id: str
    name: str
    version: str = "0.0.0"
    description: str = ""
    kind: PluginKind = PluginKind.EXTERNAL
    source: str = ""
    default_enabled: bool = True
    root: Path | None = None


@dataclass
class PluginToolManifest:
    """Tool provided by a plugin."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    required_permission: PluginToolPermission = PluginToolPermission.READ_ONLY


@dataclass
class PluginCommandManifest:
    """Command provided by a plugin."""

    name: str
    description: str = ""


@dataclass
class PluginHooks:
    """Hook commands provided by a plugin."""

    pre_tool_use: list[str] = field(default_factory=list)
    post_tool_use: list[str] = field(default_factory=list)
    post_tool_use_failure: list[str] = field(default_factory=list)


@dataclass
class PluginLifecycle:
    """Lifecycle commands for a plugin."""

    init: list[str] = field(default_factory=list)
    shutdown: list[str] = field(default_factory=list)


@dataclass
class PluginManifest:
    """Complete plugin descriptor loaded from plugin.json."""

    name: str
    version: str = "0.0.0"
    description: str = ""
    permissions: list[PluginPermission] = field(default_factory=list)
    default_enabled: bool = True
    hooks: PluginHooks = field(default_factory=PluginHooks)
    lifecycle: PluginLifecycle = field(default_factory=PluginLifecycle)
    tools: list[PluginToolManifest] = field(default_factory=list)
    commands: list[PluginCommandManifest] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ManifestValidationError:
    """Validation error details."""

    field: str
    message: str


def validate_manifest(
    manifest: PluginManifest, root: Path | None = None
) -> list[ManifestValidationError]:
    """Validate a plugin manifest for correctness.

    Checks: required fields, hook path existence, tool schema validity,
    lifecycle command existence, permission validity.
    """
    errors: list[ManifestValidationError] = []

    # Required fields
    if not manifest.name:
        errors.append(ManifestValidationError("name", "Plugin name is required"))
    if not manifest.version:
        errors.append(ManifestValidationError("version", "Plugin version is required"))

    # Validate hook paths exist
    if root:
        all_hooks = (
            manifest.hooks.pre_tool_use
            + manifest.hooks.post_tool_use
            + manifest.hooks.post_tool_use_failure
        )
        for hook_cmd in all_hooks:
            # Check if hook command references a script in the plugin directory
            hook_path = root / hook_cmd
            if not hook_path.exists() and not _is_system_command(hook_cmd):
                errors.append(ManifestValidationError(
                    "hooks",
                    f"Hook script not found: {hook_cmd} (checked {hook_path})",
                ))

        # Validate lifecycle commands
        for cmd in manifest.lifecycle.init + manifest.lifecycle.shutdown:
            cmd_path = root / cmd
            if not cmd_path.exists() and not _is_system_command(cmd):
                errors.append(ManifestValidationError(
                    "lifecycle",
                    f"Lifecycle script not found: {cmd} (checked {cmd_path})",
                ))

    # Validate tool schemas
    for tool in manifest.tools:
        if not tool.name:
            errors.append(ManifestValidationError("tools", "Tool name is required"))
        if tool.input_schema:
            schema_type = tool.input_schema.get("type")
            if schema_type and schema_type != "object":
                errors.append(ManifestValidationError(
                    f"tools.{tool.name}",
                    f"Tool input_schema type must be 'object', got '{schema_type}'",
                ))
            if "properties" not in tool.input_schema and schema_type == "object":
                errors.append(ManifestValidationError(
                    f"tools.{tool.name}",
                    "Tool input_schema must have 'properties' field",
                ))

    # Validate command names
    for cmd in manifest.commands:
        if not cmd.name:
            errors.append(ManifestValidationError("commands", "Command name is required"))
        if cmd.name.startswith("/"):
            errors.append(ManifestValidationError(
                f"commands.{cmd.name}",
                "Command name should not start with '/'",
            ))

    return errors


def _is_system_command(cmd: str) -> bool:
    """Check if a command looks like a system command (not a script path)."""
    first_word = cmd.split()[0] if cmd.strip() else ""
    return "/" not in first_word and "\\" not in first_word and "." not in first_word


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------

def load_manifest_from_directory(root: Path) -> PluginManifest | None:
    """Load a plugin manifest from a directory."""
    manifest_path = root / ".axion-plugin" / "plugin.json"
    if not manifest_path.exists():
        manifest_path = root / ".claude-plugin" / "plugin.json"  # backwards compat
        if not manifest_path.exists():
            manifest_path = root / "plugin.json"
            if not manifest_path.exists():
                return None

    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to parse manifest at %s: %s", manifest_path, exc)
        return None

    return _parse_manifest(data, root)


def _parse_manifest(data: dict[str, Any], root: Path | None = None) -> PluginManifest:
    """Parse a PluginManifest from a dict."""
    hooks = PluginHooks()
    if "hooks" in data:
        h = data["hooks"]
        hooks = PluginHooks(
            pre_tool_use=h.get("preToolUse", []),
            post_tool_use=h.get("postToolUse", []),
            post_tool_use_failure=h.get("postToolUseFailure", []),
        )

    lifecycle = PluginLifecycle()
    if "lifecycle" in data:
        lc = data["lifecycle"]
        lifecycle = PluginLifecycle(
            init=lc.get("init", []),
            shutdown=lc.get("shutdown", []),
        )

    tools = []
    for t in data.get("tools", []):
        perm = PluginToolPermission.READ_ONLY
        perm_str = t.get("requiredPermission", "read-only")
        try:
            perm = PluginToolPermission(perm_str)
        except ValueError:
            pass
        tools.append(PluginToolManifest(
            name=t.get("name", ""),
            description=t.get("description", ""),
            input_schema=t.get("inputSchema", {}),
            required_permission=perm,
        ))

    commands = []
    for c in data.get("commands", []):
        commands.append(PluginCommandManifest(
            name=c.get("name", ""),
            description=c.get("description", ""),
        ))

    permissions = []
    for p in data.get("permissions", []):
        try:
            permissions.append(PluginPermission(p))
        except ValueError:
            pass

    return PluginManifest(
        name=data.get("name", root.name if root else "unknown"),
        version=data.get("version", "0.0.0"),
        description=data.get("description", ""),
        permissions=permissions,
        default_enabled=data.get("defaultEnabled", True),
        hooks=hooks,
        lifecycle=lifecycle,
        tools=tools,
        commands=commands,
    )
