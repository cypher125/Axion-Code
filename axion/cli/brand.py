"""CLI branding.

The harness ships as "Axion Code" by default, but a downstream product built on it (for
example Rex) can rebrand the visible chrome — the welcome banner, the input prompt, and the
toolbar — without forking, by setting two environment variables:

    AXION_BRAND_NAME     shown in banners and headers (default "Axion Code")
    AXION_BRAND_PROMPT   the input prompt / toolbar label (default "axion")

Nothing about model routing, config, or storage changes; this is cosmetic only.
"""

from __future__ import annotations

import os

DEFAULT_BRAND_NAME = "Axion Code"
DEFAULT_BRAND_PROMPT = "axion"


def brand_name() -> str:
    return os.environ.get("AXION_BRAND_NAME", "").strip() or DEFAULT_BRAND_NAME


def brand_prompt() -> str:
    return os.environ.get("AXION_BRAND_PROMPT", "").strip() or DEFAULT_BRAND_PROMPT
