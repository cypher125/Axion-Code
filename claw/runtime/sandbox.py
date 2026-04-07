"""Sandbox detection and configuration.

Maps to: rust/crates/runtime/src/sandbox.rs
"""

from __future__ import annotations

import os
import platform
import sys
from dataclasses import dataclass


@dataclass
class SandboxStatus:
    """Status of the execution sandbox."""

    available: bool
    enabled: bool
    platform: str
    details: str = ""


def detect_sandbox() -> SandboxStatus:
    """Detect sandbox capabilities on the current platform."""
    plat = platform.system().lower()

    if plat == "linux":
        # Check for common sandboxing tools
        has_firejail = os.path.exists("/usr/bin/firejail")
        has_bubblewrap = os.path.exists("/usr/bin/bwrap")
        has_docker = os.path.exists("/usr/bin/docker")

        if has_firejail:
            return SandboxStatus(
                available=True, enabled=False, platform="linux",
                details="firejail available",
            )
        if has_bubblewrap:
            return SandboxStatus(
                available=True, enabled=False, platform="linux",
                details="bubblewrap available",
            )
        if has_docker:
            return SandboxStatus(
                available=True, enabled=False, platform="linux",
                details="docker available",
            )
        return SandboxStatus(
            available=False, enabled=False, platform="linux",
            details="No sandbox tools found (install firejail or bubblewrap)",
        )

    if plat == "darwin":
        return SandboxStatus(
            available=True, enabled=False, platform="macos",
            details="macOS sandbox-exec available",
        )

    if plat == "windows":
        return SandboxStatus(
            available=False, enabled=False, platform="windows",
            details="Sandboxing not supported on Windows",
        )

    return SandboxStatus(
        available=False, enabled=False, platform=plat,
        details=f"Unknown platform: {plat}",
    )
