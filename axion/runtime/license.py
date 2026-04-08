"""License key validation system for Axion Code.

License keys are validated on startup. Without a valid key,
the tool runs in limited mode (5 turns per session).

Key format: AXION-XXXXX-XXXXX-XXXXX-XXXXX
Keys are stored in ~/.axion/license.key

Validation:
- Offline: HMAC signature check (works without internet)
- Online: Optional server validation (for revocation)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

# Secret used to generate/validate keys (change this to YOUR secret)
_LICENSE_SECRET = os.environ.get(
    "AXION_LICENSE_SECRET",
    "axion-code-2026-cyrus-production-key"
)

LICENSE_FILE = Path.home() / ".axion" / "license.key"

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

TIERS = {
    "free": {
        "name": "Free",
        "price": "$0",
        "max_turns_per_session": 5,
        "max_sessions_per_day": 3,
        "tools": ["Bash", "Read", "Write", "Edit", "Glob", "Grep"],
        "features": [],
    },
    "pro": {
        "name": "Pro",
        "price": "$29 (lifetime)",
        "max_turns_per_session": 999999,
        "max_sessions_per_day": 999999,
        "tools": "all",
        "features": [
            "plan_mode", "memory", "plugins", "skills",
            "web_search", "web_fetch", "agent", "tool_search",
            "notebook_edit", "session_export", "cost_budget",
        ],
    },
    "team": {
        "name": "Team",
        "price": "$49/seat (lifetime)",
        "max_turns_per_session": 999999,
        "max_sessions_per_day": 999999,
        "tools": "all",
        "features": [
            "plan_mode", "memory", "plugins", "skills",
            "web_search", "web_fetch", "agent", "tool_search",
            "notebook_edit", "session_export", "cost_budget",
            "shared_sessions", "team_tasks", "cron_scheduler",
            "priority_support",
        ],
    },
}

FREE_TIER_TURNS = TIERS["free"]["max_turns_per_session"]
FREE_TIER_SESSIONS = TIERS["free"]["max_sessions_per_day"]

# Tools only available on paid tiers
PAID_ONLY_TOOLS = {"WebSearch", "WebFetch", "Agent", "ToolSearch", "NotebookEdit", "Skill"}


@dataclass
class LicenseInfo:
    """Parsed license information."""

    key: str
    valid: bool
    tier: str = "free"
    email: str = ""
    expires_at: int = 0  # Unix timestamp, 0 = never
    max_turns: int = FREE_TIER_TURNS
    features: list[str] | None = None

    @property
    def is_expired(self) -> bool:
        if self.expires_at == 0:
            return False
        return int(time.time()) > self.expires_at

    @property
    def is_active(self) -> bool:
        return self.valid and not self.is_expired


# ---------------------------------------------------------------------------
# Key generation (use this to create keys for customers)
# ---------------------------------------------------------------------------

def generate_license_key(
    email: str,
    tier: str = "pro",
    expires_days: int = 365,
) -> str:
    """Generate a signed license key.

    Call this from a separate admin script, NOT from the client.
    """
    import secrets

    # Create payload
    payload = {
        "email": email,
        "tier": tier,
        "created": int(time.time()),
        "expires": int(time.time()) + (expires_days * 86400),
        "nonce": secrets.token_hex(4),
    }
    payload_str = json.dumps(payload, sort_keys=True)

    # Sign with HMAC
    sig = hmac.new(
        _LICENSE_SECRET.encode(), payload_str.encode(), hashlib.sha256
    ).hexdigest()[:20]

    # Encode as compact key using base64url (no padding chars)
    import base64
    encoded = base64.urlsafe_b64encode(payload_str.encode()).decode().rstrip("=")

    # Format: AXION-<sig_10chars>-<full_encoded_payload>
    return f"AXION-{sig[:10]}-{encoded}"


def validate_license_key(key: str) -> LicenseInfo:
    """Validate a license key and return license info.

    Checks HMAC signature offline — no internet needed.
    """
    if not key or not key.startswith("AXION-"):
        return LicenseInfo(key=key, valid=False, tier="free", max_turns=FREE_TIER_TURNS)

    try:
        # Format: AXION-<sig_10chars>-<base64url_payload>
        # Split only into 3 parts: AXION, sig, payload
        idx1 = key.index("-", 0)       # After "AXION"
        idx2 = key.index("-", idx1 + 1)  # After sig
        sig_part = key[idx1 + 1:idx2]
        encoded = key[idx2 + 1:]

        if len(sig_part) != 10:
            return LicenseInfo(key=key, valid=False, tier="free", max_turns=FREE_TIER_TURNS)

        # Decode payload (base64url, add padding back)
        import base64
        padding = 4 - len(encoded) % 4
        if padding != 4:
            encoded += "=" * padding

        payload_str = base64.urlsafe_b64decode(encoded).decode()
        payload = json.loads(payload_str)

        # Verify HMAC signature
        expected_sig = hmac.new(
            _LICENSE_SECRET.encode(), payload_str.encode(), hashlib.sha256
        ).hexdigest()[:10]

        if not hmac.compare_digest(sig_part, expected_sig):
            return LicenseInfo(key=key, valid=False, tier="free", max_turns=FREE_TIER_TURNS)

        # Key is valid — extract tier info from definitions
        tier = payload.get("tier", "pro")
        tier_def = TIERS.get(tier, TIERS["free"])
        max_turns_val: int = tier_def["max_turns_per_session"]  # type: ignore[assignment]
        features: list[str] = tier_def["features"]  # type: ignore[assignment]

        return LicenseInfo(
            key=key,
            valid=True,
            tier=tier,
            email=payload.get("email", ""),
            expires_at=payload.get("expires", 0),
            max_turns=max_turns_val,
            features=features,
        )

    except Exception:
        return LicenseInfo(key=key, valid=False, tier="free", max_turns=FREE_TIER_TURNS)


# ---------------------------------------------------------------------------
# License file management
# ---------------------------------------------------------------------------

def save_license(key: str) -> None:
    """Save license key to disk."""
    LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
    LICENSE_FILE.write_text(key.strip(), encoding="utf-8")
    try:
        os.chmod(LICENSE_FILE, 0o600)
    except OSError:
        pass


def load_license() -> LicenseInfo:
    """Load and validate the stored license key."""
    if not LICENSE_FILE.exists():
        return LicenseInfo(key="", valid=False, tier="free", max_turns=FREE_TIER_TURNS)

    key = LICENSE_FILE.read_text(encoding="utf-8").strip()
    if not key:
        return LicenseInfo(key="", valid=False, tier="free", max_turns=FREE_TIER_TURNS)

    return validate_license_key(key)


def clear_license() -> None:
    """Remove stored license."""
    if LICENSE_FILE.exists():
        LICENSE_FILE.unlink()


# ---------------------------------------------------------------------------
# License check for CLI
# ---------------------------------------------------------------------------

def check_license_or_warn(console: object | None = None) -> LicenseInfo:
    """Check license and show warning if on free tier.

    Returns the license info for the runtime to enforce limits.
    """
    info = load_license()

    if console and hasattr(console, "print"):
        if not info.valid:
            console.print(
                "\n[dim]Free tier: limited to "
                f"{FREE_TIER_TURNS} turns per session. "
                "Run [bold]axion activate <key>[/bold] to unlock.[/dim]\n"
            )
        elif info.is_expired:
            console.print(
                "\n[yellow]License expired. "
                "Run [bold]axion activate <key>[/bold] with a new key.[/yellow]\n"
            )
        elif info.tier == "starter":
            console.print(f"\n[dim]Starter plan ({info.email})[/dim]\n")

    return info


def is_tool_allowed(license_info: LicenseInfo, tool_name: str) -> bool:
    """Check if a tool is allowed under the current license tier."""
    if license_info.is_active:
        tier_def = TIERS.get(license_info.tier, TIERS["free"])
        if tier_def["tools"] == "all":
            return True
        return tool_name in tier_def["tools"]  # type: ignore[operator]

    # Free tier: block paid-only tools
    return tool_name not in PAID_ONLY_TOOLS


def get_upgrade_message(current_tier: str) -> str:
    """Get a message suggesting the user upgrade."""
    if current_tier == "free":
        return (
            "Upgrade to Pro for $29 (lifetime) — unlock all tools, "
            "unlimited turns, plan mode, web search, agent, and more.\n"
            "  Visit: https://axioncode.dev/pricing\n"
            "  Then: axion activate <your-key>"
        )
    if current_tier == "pro":
        return (
            "Upgrade to Team for $49/seat (lifetime) — "
            "shared sessions, team tasks, cron scheduler, priority support.\n"
            "  Visit: https://axioncode.dev/pricing"
        )
    return ""


def format_license_status(info: LicenseInfo) -> str:
    """Format license info for display."""
    if not info.valid:
        return (
            f"Plan: Free\n"
            f"  Turns: {FREE_TIER_TURNS}/session\n"
            f"  Tools: basic (6 of 13)\n"
            f"  Upgrade: axion activate <key> for unlimited"
        )

    tier_def = TIERS.get(info.tier, TIERS["free"])
    lines = [
        f"Plan: {tier_def['name']}",  # type: ignore[index]
        f"  Email: {info.email}" if info.email else "",
        "  Turns: unlimited" if info.max_turns > 1000 else f"  Turns: {info.max_turns}/session",
        "  Tools: all (13)" if tier_def["tools"] == "all" else f"  Tools: {len(tier_def['tools'])}",  # type: ignore[arg-type]
    ]
    if info.expires_at:
        from datetime import datetime
        exp = datetime.fromtimestamp(info.expires_at).strftime("%Y-%m-%d")
        lines.append(f"  Expires: {exp}")
    else:
        lines.append("  Expires: never (lifetime)")

    upgrade = get_upgrade_message(info.tier)
    if upgrade:
        lines.append(f"\n  {upgrade.splitlines()[0]}")

    return "\n".join(line for line in lines if line)
