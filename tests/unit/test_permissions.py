"""Tests for permission system."""

from claw.runtime.permissions import (
    PermissionAllow,
    PermissionDeny,
    PermissionMode,
    PermissionPolicy,
)


def test_allow_mode_permits_all():
    policy = PermissionPolicy(mode=PermissionMode.ALLOW)
    result = policy.authorize("Bash")
    assert isinstance(result, PermissionAllow)


def test_read_only_permits_read():
    policy = PermissionPolicy(mode=PermissionMode.READ_ONLY)
    result = policy.authorize("Read")
    assert isinstance(result, PermissionAllow)


def test_read_only_denies_write():
    policy = PermissionPolicy(mode=PermissionMode.READ_ONLY)
    result = policy.authorize("Bash")
    assert isinstance(result, PermissionDeny)
    assert "workspace-write" in result.reason


def test_workspace_write_permits_bash():
    policy = PermissionPolicy(mode=PermissionMode.WORKSPACE_WRITE)
    result = policy.authorize("Bash")
    assert isinstance(result, PermissionAllow)


def test_workspace_write_permits_read():
    policy = PermissionPolicy(mode=PermissionMode.WORKSPACE_WRITE)
    result = policy.authorize("Read")
    assert isinstance(result, PermissionAllow)


def test_deny_rules():
    policy = PermissionPolicy(
        mode=PermissionMode.ALLOW,
        deny_rules=["Bash"],
    )
    result = policy.authorize("Bash")
    assert isinstance(result, PermissionDeny)

    result = policy.authorize("Read")
    assert isinstance(result, PermissionAllow)


def test_allow_rules_override():
    policy = PermissionPolicy(
        mode=PermissionMode.READ_ONLY,
        allow_rules=["Bash"],
    )
    result = policy.authorize("Bash")
    assert isinstance(result, PermissionAllow)


def test_wildcard_deny():
    policy = PermissionPolicy(
        mode=PermissionMode.ALLOW,
        deny_rules=["*"],
    )
    result = policy.authorize("Read")
    assert isinstance(result, PermissionDeny)
