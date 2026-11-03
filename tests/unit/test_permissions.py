"""Tests for permission system."""

from axion.runtime.permissions import (
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


def test_allow_once_is_not_cached():
    """'allow once' must not persist as 'allow always' (one yes shouldn't whitelist a tool)."""
    from axion.runtime.permissions import PermissionAllow, PermissionDecisionKind, PermissionMode, PermissionPolicy
    policy = PermissionPolicy(mode=PermissionMode.PROMPT) if hasattr(PermissionMode, "PROMPT") else PermissionPolicy()
    # ALLOW_ONCE must not be remembered
    policy.remember_decision("Bash", PermissionAllow(), kind=PermissionDecisionKind.ALLOW_ONCE)
    # ALLOW_ALWAYS is remembered
    policy.remember_decision("Write", PermissionAllow(), kind=PermissionDecisionKind.ALLOW_ALWAYS)
    # Only the cached-always one should be in the remembered set
    key_bash = f"Bash:{policy.mode.value}"
    key_write = f"Write:{policy.mode.value}"
    assert key_bash not in policy._decision_cache
    assert key_write in policy._decision_cache


def test_command_scoped_permission_rules():
    """Scoped rules like Bash(git *) / Bash(rm *) match on the command, not just the tool name."""
    import json

    from axion.runtime.permissions import PermissionAllow, PermissionDeny, PermissionMode, PermissionPolicy
    policy = PermissionPolicy(mode=PermissionMode.PROMPT)
    policy.allow_rules = ["Bash(git *)", "Edit(src/*)"]
    policy.deny_rules = ["Bash(rm *)"]

    def check(tool, inp):
        return policy.authorize(tool, json.dumps(inp))

    assert isinstance(check("Bash", {"command": "git status"}), PermissionAllow)
    assert isinstance(check("Bash", {"command": "rm -rf /"}), PermissionDeny)         # denied by scope
    # a Bash command matching neither rule falls through to mode handling (PROMPT -> needs prompt deny)
    other = check("Bash", {"command": "curl evil"})
    assert isinstance(other, PermissionDeny) and "__NEEDS_PROMPT__" in other.reason
    # path-scoped Edit
    assert isinstance(check("Edit", {"file_path": "src/app.py"}), PermissionAllow)
    assert not isinstance(check("Edit", {"file_path": "secrets.env"}), PermissionAllow)


def test_matches_rule_backward_compat():
    from axion.runtime.permissions import PermissionPolicy
    assert PermissionPolicy._matches_rule("*", "Bash")
    assert PermissionPolicy._matches_rule("Bash", "Bash")
    assert PermissionPolicy._matches_rule("Web*", "WebFetch")
    assert not PermissionPolicy._matches_rule("Read", "Bash")
