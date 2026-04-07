"""Tests for usage tracking."""

from axion.runtime.usage import (
    TokenUsage,
    UsageTracker,
    format_usd,
    pricing_for_model,
)


def test_token_usage_total():
    usage = TokenUsage(
        input_tokens=1000,
        output_tokens=500,
        cache_creation_input_tokens=100,
        cache_read_input_tokens=200,
    )
    assert usage.total_tokens() == 1800


def test_cost_estimation():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=500_000,
        cache_creation_input_tokens=100_000,
        cache_read_input_tokens=200_000,
    )
    cost = usage.estimate_cost_usd()
    assert cost.total_cost_usd() > 0
    assert cost.input_cost_usd == 3.0   # 1M * $3/M (Sonnet default)
    assert cost.output_cost_usd == 7.5  # 500K * $15/M (Sonnet default)


def test_format_usd():
    assert format_usd(0.0) == "$0.0000"
    assert format_usd(1.5) == "$1.5000"
    assert format_usd(54.675) == "$54.6750"


def test_pricing_for_model():
    haiku = pricing_for_model("claude-haiku-4-5-20251213")
    assert haiku is not None
    assert haiku.input_cost_per_million == 1.0

    opus = pricing_for_model("claude-opus-4-6")
    assert opus is not None
    assert opus.input_cost_per_million == 15.0

    unknown = pricing_for_model("unknown-model")
    assert unknown is None


def test_usage_tracker():
    tracker = UsageTracker()
    tracker.record_turn(TokenUsage(input_tokens=100, output_tokens=50))
    tracker.record_turn(TokenUsage(input_tokens=200, output_tokens=100))
    assert tracker.turn_count == 2
    assert tracker.total.input_tokens == 300
    assert tracker.total.output_tokens == 150


def test_iadd():
    a = TokenUsage(input_tokens=10, output_tokens=20)
    b = TokenUsage(input_tokens=5, output_tokens=15)
    a += b
    assert a.input_tokens == 15
    assert a.output_tokens == 35
