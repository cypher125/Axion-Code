"""Prompt caching support.

Maps to: rust/crates/api/src/prompt_cache.rs
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PromptCacheConfig:
    """Configuration for prompt caching behavior."""

    enabled: bool = True
    scope: str = "session"


@dataclass
class PromptCache:
    """Tracks prompt cache state across requests."""

    config: PromptCacheConfig = field(default_factory=PromptCacheConfig)
    cache_hits: int = 0
    cache_misses: int = 0

    def record_hit(self, tokens: int) -> None:
        self.cache_hits += 1

    def record_miss(self) -> None:
        self.cache_misses += 1
