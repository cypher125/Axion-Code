"""Tests for configuration system."""

import json
from pathlib import Path

from claw.runtime.config import ConfigLoader, RuntimeConfig


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
