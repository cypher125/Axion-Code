"""Token usage tracking and cost estimation.

Maps to: rust/crates/runtime/src/usage.rs
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Default pricing (Sonnet 4 tier - $3 input / $15 output per million tokens)
DEFAULT_INPUT_COST_PER_MILLION = 3.0
DEFAULT_OUTPUT_COST_PER_MILLION = 15.0
DEFAULT_CACHE_CREATION_COST_PER_MILLION = 3.75
DEFAULT_CACHE_READ_COST_PER_MILLION = 0.3


@dataclass
class ModelPricing:
    """Per-million-token pricing for cost estimation."""

    input_cost_per_million: float = DEFAULT_INPUT_COST_PER_MILLION
    output_cost_per_million: float = DEFAULT_OUTPUT_COST_PER_MILLION
    cache_creation_cost_per_million: float = DEFAULT_CACHE_CREATION_COST_PER_MILLION
    cache_read_cost_per_million: float = DEFAULT_CACHE_READ_COST_PER_MILLION

    @classmethod
    def default_sonnet_tier(cls) -> ModelPricing:
        return cls()


@dataclass
class TokenUsage:
    """Token counters accumulated for a conversation turn or session."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def total_tokens(self) -> int:
        return (
            self.input_tokens
            + self.output_tokens
            + self.cache_creation_input_tokens
            + self.cache_read_input_tokens
        )

    def estimate_cost_usd(self) -> UsageCostEstimate:
        return self.estimate_cost_usd_with_pricing(ModelPricing.default_sonnet_tier())

    def estimate_cost_usd_with_pricing(self, pricing: ModelPricing) -> UsageCostEstimate:
        return UsageCostEstimate(
            input_cost_usd=_cost_for_tokens(self.input_tokens, pricing.input_cost_per_million),
            output_cost_usd=_cost_for_tokens(
                self.output_tokens, pricing.output_cost_per_million
            ),
            cache_creation_cost_usd=_cost_for_tokens(
                self.cache_creation_input_tokens,
                pricing.cache_creation_cost_per_million,
            ),
            cache_read_cost_usd=_cost_for_tokens(
                self.cache_read_input_tokens,
                pricing.cache_read_cost_per_million,
            ),
        )

    def __iadd__(self, other: TokenUsage) -> TokenUsage:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens
        return self

    def summary_lines(self, label: str, model: str | None = None) -> list[str]:
        pricing = pricing_for_model(model) if model else None
        cost = (
            self.estimate_cost_usd_with_pricing(pricing)
            if pricing
            else self.estimate_cost_usd()
        )
        model_suffix = f" model={model}" if model else ""
        return [
            f"{label}: total_tokens={self.total_tokens()} "
            f"input={self.input_tokens} output={self.output_tokens} "
            f"cache_write={self.cache_creation_input_tokens} "
            f"cache_read={self.cache_read_input_tokens} "
            f"estimated_cost={format_usd(cost.total_cost_usd())}{model_suffix}",
            f"  cost breakdown: input={format_usd(cost.input_cost_usd)} "
            f"output={format_usd(cost.output_cost_usd)} "
            f"cache_write={format_usd(cost.cache_creation_cost_usd)} "
            f"cache_read={format_usd(cost.cache_read_cost_usd)}",
        ]


@dataclass
class UsageCostEstimate:
    """Estimated dollar cost derived from a TokenUsage sample."""

    input_cost_usd: float = 0.0
    output_cost_usd: float = 0.0
    cache_creation_cost_usd: float = 0.0
    cache_read_cost_usd: float = 0.0

    def total_cost_usd(self) -> float:
        return (
            self.input_cost_usd
            + self.output_cost_usd
            + self.cache_creation_cost_usd
            + self.cache_read_cost_usd
        )


def pricing_for_model(model: str | None) -> ModelPricing | None:
    """Returns pricing metadata for a known model alias or family."""
    if model is None:
        return None
    normalized = model.lower()
    if "haiku" in normalized:
        return ModelPricing(
            input_cost_per_million=1.0,
            output_cost_per_million=5.0,
            cache_creation_cost_per_million=1.25,
            cache_read_cost_per_million=0.1,
        )
    if "opus" in normalized:
        return ModelPricing(
            input_cost_per_million=5.0,   # Opus 4.6: $5/MTok input
            output_cost_per_million=25.0,  # Opus 4.6: $25/MTok output
            cache_creation_cost_per_million=6.25,
            cache_read_cost_per_million=0.5,
        )
    if "sonnet" in normalized:
        return ModelPricing.default_sonnet_tier()
    # OpenAI models
    if "gpt-4o-mini" in normalized or "4o-mini" in normalized:
        return ModelPricing(
            input_cost_per_million=0.15,
            output_cost_per_million=0.60,
            cache_creation_cost_per_million=0.075,
            cache_read_cost_per_million=0.075,
        )
    if "gpt-4o" in normalized or "4o" in normalized:
        return ModelPricing(
            input_cost_per_million=2.50,
            output_cost_per_million=10.0,
            cache_creation_cost_per_million=1.25,
            cache_read_cost_per_million=1.25,
        )
    if normalized in ("o1", "o3"):
        return ModelPricing(
            input_cost_per_million=15.0,
            output_cost_per_million=60.0,
            cache_creation_cost_per_million=7.5,
            cache_read_cost_per_million=7.5,
        )
    if "o3-mini" in normalized:
        return ModelPricing(
            input_cost_per_million=1.10,
            output_cost_per_million=4.40,
            cache_creation_cost_per_million=0.55,
            cache_read_cost_per_million=0.55,
        )
    # xAI
    if "grok" in normalized:
        return ModelPricing(
            input_cost_per_million=5.0,
            output_cost_per_million=15.0,
            cache_creation_cost_per_million=2.5,
            cache_read_cost_per_million=2.5,
        )
    return None


def _cost_for_tokens(tokens: int, cost_per_million: float) -> float:
    return (tokens / 1_000_000) * cost_per_million


def format_usd(value: float) -> str:
    """Format a USD value with 4 decimal places."""
    return f"${value:.4f}"


# ---------------------------------------------------------------------------
# Usage tracker (accumulates across turns)
# ---------------------------------------------------------------------------

@dataclass
class UsageTracker:
    """Accumulates token usage across multiple turns."""

    total: TokenUsage = field(default_factory=TokenUsage)
    turn_count: int = 0
    model: str | None = None

    def record_turn(self, usage: TokenUsage) -> None:
        self.total += usage
        self.turn_count += 1

    def summary_lines(self) -> list[str]:
        return self.total.summary_lines("Session total", self.model)

    @classmethod
    def from_session(cls, session: Any) -> UsageTracker:
        """Build tracker from existing session messages' usage data."""
        tracker = cls()
        for msg in getattr(session, "messages", []):
            if msg.usage is not None:
                tracker.record_turn(msg.usage)
        return tracker
