"""Plugin manager and registry with lifecycle execution.

Maps to: rust/crates/plugins/src/lib.rs (PluginManager, PluginRegistry)
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from axion.plugins.manifest import (
    ManifestValidationError,
    PluginKind,
    PluginManifest,
    PluginMetadata,
    load_manifest_from_directory,
    validate_manifest,
)

logger = logging.getLogger(__name__)


@dataclass
class PluginSummary:
    """Summary of an installed plugin."""

    id: str
    name: str
    version: str
    description: str
    enabled: bool
    kind: PluginKind
    tool_count: int = 0
    command_count: int = 0
    hook_count: int = 0
    validation_errors: list[str] = field(default_factory=list)


@dataclass
class PluginLoadFailure:
    """Error details during plugin loading."""

    plugin_id: str
    error: str
    path: str = ""


@dataclass
class PluginRegistryReport:
    """Report of loaded/failed plugins."""

    loaded: list[PluginSummary]
    failed: list[PluginLoadFailure]


@dataclass
class RegisteredPlugin:
    """A plugin with its metadata and manifest."""

    metadata: PluginMetadata
    manifest: PluginManifest
    enabled: bool = True
    validation_errors: list[ManifestValidationError] = field(default_factory=list)


@dataclass
class InstalledPluginRecord:
    """Persistence record of an installed plugin."""

    plugin_id: str
    source: str
    installed_at_ms: int = 0
    enabled: bool = True


class PluginRegistry:
    """Registry of all discovered plugins.

    Maps to: rust/crates/plugins/src/lib.rs::PluginRegistry
    """

    def __init__(self) -> None:
        self._plugins: dict[str, RegisteredPlugin] = {}

    def register(self, plugin: RegisteredPlugin) -> None:
        self._plugins[plugin.metadata.id] = plugin

    def get(self, plugin_id: str) -> RegisteredPlugin | None:
        return self._plugins.get(plugin_id)

    def all_plugins(self) -> list[RegisteredPlugin]:
        return list(self._plugins.values())

    def enabled_plugins(self) -> list[RegisteredPlugin]:
        return [p for p in self._plugins.values() if p.enabled]

    def summaries(self) -> list[PluginSummary]:
        return [
            PluginSummary(
                id=p.metadata.id,
                name=p.metadata.name,
                version=p.metadata.version,
                description=p.metadata.description,
                enabled=p.enabled,
                kind=p.metadata.kind,
                tool_count=len(p.manifest.tools),
                command_count=len(p.manifest.commands),
                hook_count=(
                    len(p.manifest.hooks.pre_tool_use)
                    + len(p.manifest.hooks.post_tool_use)
                    + len(p.manifest.hooks.post_tool_use_failure)
                ),
                validation_errors=[e.message for e in p.validation_errors],
            )
            for p in self._plugins.values()
        ]

    def aggregated_hooks(self) -> dict[str, list[str]]:
        """Collect all hook commands from enabled plugins."""
        hooks: dict[str, list[str]] = {
            "pre_tool_use": [],
            "post_tool_use": [],
            "post_tool_use_failure": [],
        }
        for plugin in self.enabled_plugins():
            hooks["pre_tool_use"].extend(plugin.manifest.hooks.pre_tool_use)
            hooks["post_tool_use"].extend(plugin.manifest.hooks.post_tool_use)
            hooks["post_tool_use_failure"].extend(plugin.manifest.hooks.post_tool_use_failure)
        return hooks

    def remove(self, plugin_id: str) -> RegisteredPlugin | None:
        return self._plugins.pop(plugin_id, None)


class PluginManager:
    """Manages plugin lifecycle: install, enable, disable, uninstall, init, shutdown.

    Maps to: rust/crates/plugins/src/lib.rs::PluginManager
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or (Path.home() / ".axion" / "plugins")
        self.registry = PluginRegistry()
        self._installed_registry_path = self.config_dir / ".installed.json"

    def discover_plugins(self) -> PluginRegistryReport:
        """Discover and register plugins from the config directory."""
        loaded: list[PluginSummary] = []
        failed: list[PluginLoadFailure] = []

        if not self.config_dir.exists():
            return PluginRegistryReport(loaded=loaded, failed=failed)

        # Load installed registry
        installed_records = self._load_installed_records()

        for plugin_dir in self.config_dir.iterdir():
            if not plugin_dir.is_dir() or plugin_dir.name.startswith("."):
                continue

            manifest = load_manifest_from_directory(plugin_dir)
            if manifest is None:
                failed.append(PluginLoadFailure(
                    plugin_id=plugin_dir.name,
                    error="Failed to load plugin manifest",
                    path=str(plugin_dir),
                ))
                continue

            # Validate manifest
            errors = validate_manifest(manifest, root=plugin_dir)

            metadata = PluginMetadata(
                id=plugin_dir.name,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description,
                kind=PluginKind.EXTERNAL,
                source=str(plugin_dir),
                default_enabled=manifest.default_enabled,
                root=plugin_dir,
            )

            # Check installed records for enabled state
            record = installed_records.get(plugin_dir.name)
            enabled = record.enabled if record else manifest.default_enabled

            plugin = RegisteredPlugin(
                metadata=metadata,
                manifest=manifest,
                enabled=enabled,
                validation_errors=errors,
            )
            self.registry.register(plugin)

        loaded = self.registry.summaries()
        return PluginRegistryReport(loaded=loaded, failed=failed)

    def install(self, source: Path) -> PluginSummary | None:
        """Install a plugin from a directory."""
        manifest = load_manifest_from_directory(source)
        if manifest is None:
            logger.error("No valid plugin manifest found at %s", source)
            return None

        # Validate
        errors = validate_manifest(manifest, root=source)
        if any(e.field == "name" for e in errors):
            logger.error("Plugin manifest has critical errors: %s", errors)
            return None

        # Derive plugin ID
        plugin_id = manifest.name.lower().replace(" ", "-")
        target = self.config_dir / plugin_id

        # Copy to config dir
        self.config_dir.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(source, target)

        metadata = PluginMetadata(
            id=plugin_id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            kind=PluginKind.EXTERNAL,
            source=str(source),
            root=target,
        )

        plugin = RegisteredPlugin(
            metadata=metadata, manifest=manifest, validation_errors=errors,
        )
        self.registry.register(plugin)

        # Save installed record
        self._save_installed_record(plugin_id, str(source), enabled=True)

        # Run init lifecycle commands
        self._run_lifecycle_commands(manifest.lifecycle.init, target)

        return PluginSummary(
            id=plugin_id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            enabled=True,
            kind=PluginKind.EXTERNAL,
            tool_count=len(manifest.tools),
            command_count=len(manifest.commands),
        )

    def enable(self, plugin_id: str) -> bool:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            return False
        plugin.enabled = True
        self._save_installed_record(plugin_id, plugin.metadata.source, enabled=True)
        return True

    def disable(self, plugin_id: str) -> bool:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            return False
        plugin.enabled = False
        self._save_installed_record(plugin_id, plugin.metadata.source, enabled=False)
        return True

    def uninstall(self, plugin_id: str) -> bool:
        plugin = self.registry.get(plugin_id)
        if plugin is None:
            return False

        # Run shutdown lifecycle commands
        if plugin.metadata.root:
            self._run_lifecycle_commands(
                plugin.manifest.lifecycle.shutdown, plugin.metadata.root,
            )

        # Remove from disk
        if plugin.metadata.root and plugin.metadata.root.exists():
            shutil.rmtree(plugin.metadata.root)

        # Remove from registry
        self.registry.remove(plugin_id)

        # Remove from installed records
        self._remove_installed_record(plugin_id)
        return True

    def update(self, plugin_id: str, source: Path) -> PluginSummary | None:
        """Update a plugin by uninstalling and reinstalling."""
        self.uninstall(plugin_id)
        return self.install(source)

    def shutdown_all(self) -> None:
        """Run shutdown lifecycle for all enabled plugins."""
        for plugin in self.registry.enabled_plugins():
            if plugin.metadata.root:
                self._run_lifecycle_commands(
                    plugin.manifest.lifecycle.shutdown, plugin.metadata.root,
                )

    # -----------------------------------------------------------------------
    # Lifecycle execution
    # -----------------------------------------------------------------------

    @staticmethod
    def _run_lifecycle_commands(commands: list[str], cwd: Path) -> None:
        """Execute lifecycle commands in the plugin directory."""
        for cmd in commands:
            try:
                result = subprocess.run(
                    cmd,
                    shell=True,
                    cwd=str(cwd),
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    logger.warning(
                        "Plugin lifecycle command failed: %s (exit %d): %s",
                        cmd, result.returncode, result.stderr,
                    )
            except subprocess.TimeoutExpired:
                logger.warning("Plugin lifecycle command timed out: %s", cmd)
            except Exception as exc:
                logger.warning("Plugin lifecycle command error: %s: %s", cmd, exc)

    # -----------------------------------------------------------------------
    # Installed plugin persistence
    # -----------------------------------------------------------------------

    def _load_installed_records(self) -> dict[str, InstalledPluginRecord]:
        """Load the installed plugin registry from disk."""
        if not self._installed_registry_path.exists():
            return {}
        try:
            data = json.loads(self._installed_registry_path.read_text(encoding="utf-8"))
            records = {}
            for plugin_id, record_data in data.items():
                records[plugin_id] = InstalledPluginRecord(
                    plugin_id=plugin_id,
                    source=record_data.get("source", ""),
                    installed_at_ms=record_data.get("installed_at_ms", 0),
                    enabled=record_data.get("enabled", True),
                )
            return records
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_installed_record(
        self, plugin_id: str, source: str, enabled: bool
    ) -> None:
        """Save an installed plugin record."""
        records = self._load_installed_records()
        import time

        records[plugin_id] = InstalledPluginRecord(
            plugin_id=plugin_id,
            source=source,
            installed_at_ms=int(time.time() * 1000),
            enabled=enabled,
        )
        self._write_installed_records(records)

    def _remove_installed_record(self, plugin_id: str) -> None:
        records = self._load_installed_records()
        records.pop(plugin_id, None)
        self._write_installed_records(records)

    def _write_installed_records(
        self, records: dict[str, InstalledPluginRecord]
    ) -> None:
        self._installed_registry_path.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        for pid, record in records.items():
            data[pid] = {
                "source": record.source,
                "installed_at_ms": record.installed_at_ms,
                "enabled": record.enabled,
            }
        self._installed_registry_path.write_text(
            json.dumps(data, indent=2), encoding="utf-8",
        )
