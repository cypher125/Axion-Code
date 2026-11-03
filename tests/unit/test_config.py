"""Tests for configuration system."""

import json

from axion.runtime.config import ConfigLoader, RuntimeConfig


def test_config_loader_empty(tmp_path):
    loader = ConfigLoader(project_dir=tmp_path)
    config = loader.load()
    assert isinstance(config, RuntimeConfig)
    assert config.merged == {} or isinstance(config.merged, dict)


def test_config_loader_project_config(tmp_path):
    # Create a .claude.json
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({
        "permissions": {"defaultMode": "allow"},
        "model": "claude-opus-4-6",
    }))

    loader = ConfigLoader(project_dir=tmp_path)
    config = loader.load()
    assert config.feature_config.permission_mode == "allow"
    assert config.feature_config.model == "claude-opus-4-6"


def test_config_deep_merge(tmp_path):
    # Create project config
    claude_json = tmp_path / ".claude.json"
    claude_json.write_text(json.dumps({
        "permissions": {"defaultMode": "prompt"},
        "model": "claude-sonnet-4-6",
    }))

    # Create local override
    local_dir = tmp_path / ".claude"
    local_dir.mkdir()
    local_settings = local_dir / "settings.json"
    local_settings.write_text(json.dumps({
        "permissions": {"defaultMode": "allow"},
    }))

    loader = ConfigLoader(project_dir=tmp_path)
    config = loader.load()
    # Local should override project
    assert config.feature_config.permission_mode == "allow"
    # Model should be preserved from project
    assert config.feature_config.model == "claude-sonnet-4-6"


def test_permission_lists_union_not_overwrite(tmp_path):
    from axion.runtime.config import ConfigLoader
    base = {"permissions": {"allowedTools": ["Read", "Grep"]}}
    override = {"permissions": {"allowedTools": ["Grep", "Bash"]}}
    ConfigLoader._deep_merge(base, override)
    assert set(base["permissions"]["allowedTools"]) == {"Read", "Grep", "Bash"}


def test_deep_merge_does_not_alias_source(tmp_path):
    from axion.runtime.config import ConfigLoader
    base = {}
    override = {"nested": {"x": 1}}
    ConfigLoader._deep_merge(base, override)
    base["nested"]["x"] = 99
    assert override["nested"]["x"] == 1  # source not mutated
