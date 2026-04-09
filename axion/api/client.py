"""Provider client factory - dispatches to Anthropic or OpenAI-compatible.

Maps to: rust/crates/api/src/client.rs
"""

from __future__ import annotations

import enum
from typing import AsyncIterator

from axion.api.anthropic import AnthropicClient, AuthCredentials
from axion.api.error import ApiError
from axion.api.ollama import OllamaClient, is_ollama_model
from axion.api.openai_compat import OpenAiCompatClient, OpenAiCompatConfig
from axion.api.types import MessageRequest, MessageResponse, StreamEvent

# Model alias resolution
MODEL_ALIASES: dict[str, str] = {
    # Anthropic Claude
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5",
    "opus[1m]": "claude-opus-4-6",
    "sonnet[1m]": "claude-sonnet-4-6",
    "haiku[1m]": "claude-haiku-4-5",

    # OpenAI — GPT-4 series
    "gpt4": "gpt-4o",
    "gpt4o": "gpt-4o",
    "gpt-4": "gpt-4o",
    "4o": "gpt-4o",
    "gpt-4o-mini": "gpt-4o-mini",
    "4o-mini": "gpt-4o-mini",
    "gpt-4.1": "gpt-4.1",
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt-4.1-nano": "gpt-4.1-nano",

    # OpenAI — GPT-5 series
    "gpt5": "gpt-5",
    "gpt-5": "gpt-5",
    "5": "gpt-5",
    "gpt-5-mini": "gpt-5-mini",
    "5-mini": "gpt-5-mini",
    "gpt-5-nano": "gpt-5-nano",
    "5-nano": "gpt-5-nano",
    "gpt-5-pro": "gpt-5-pro",
    "5-pro": "gpt-5-pro",
    "gpt-5.4": "gpt-5.4",
    "gpt-5.4-mini": "gpt-5.4-mini",
    "gpt-5.4-nano": "gpt-5.4-nano",
    "gpt-5.4-pro": "gpt-5.4-pro",

    # OpenAI — Codex (uses Responses API — map to GPT-5 chat equivalents for now)
    "codex": "gpt-5",
    "codex-mini": "gpt-5-mini",

    # OpenAI — o-series (reasoning)
    "o1": "o1",
    "o1-pro": "o1-pro",
    "o3": "o3",
    "o3-mini": "o3-mini",
    "o3-pro": "o3-pro",
    "o4-mini": "o4-mini",

    # xAI
    "grok": "grok-2",
    "grok2": "grok-2",
    "grok-3": "grok-3",

    # Ollama / local
    "local": "llama3.1",
    "llama": "llama3.1",
    "llama4": "llama4-scout",
    "mistral": "mistral",
    "codellama": "codellama",
    "deepseek": "deepseek-coder-v2",
    "phi": "phi3",
    "gemma": "gemma2",
    "qwen": "qwen2.5-coder",
}


class ProviderKind(enum.Enum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    XAI = "xai"
    OLLAMA = "ollama"


def resolve_model_alias(model: str | None) -> str:
    """Resolve short model aliases to full model IDs.

    Handles Claude Code format like "opus[1m]", "sonnet[1m]".
    Returns default model if None.
    """
    if not model:
        return "claude-sonnet-4-6"
    lower = model.lower().strip()

    # Direct match
    if lower in MODEL_ALIASES:
        return MODEL_ALIASES[lower]

    # Strip [context] suffix (e.g. "opus[1m]" -> "opus")
    import re
    stripped = re.sub(r"\[.*?\]$", "", lower).strip()
    if stripped in MODEL_ALIASES:
        return MODEL_ALIASES[stripped]

    return model


def detect_provider_kind(model: str) -> ProviderKind:
    """Detect the provider from a model name."""
    resolved = resolve_model_alias(model)
    if resolved.startswith("claude-"):
        return ProviderKind.ANTHROPIC
    if resolved.startswith("grok-"):
        return ProviderKind.XAI
    if any(resolved.startswith(p) for p in ("gpt-", "o1", "o3", "o4", "codex", "gpt-5")):
        return ProviderKind.OPENAI
    if is_ollama_model(resolved):
        return ProviderKind.OLLAMA
    # Default to Anthropic
    return ProviderKind.ANTHROPIC


# Max tokens per model
MAX_TOKENS_FOR_MODEL: dict[str, int] = {
    "claude-opus-4-6": 32_000,
    "claude-sonnet-4-6": 64_000,
    "claude-haiku-4-5": 64_000,
}

DEFAULT_MAX_TOKENS = 16_000


def max_tokens_for_model(model: str) -> int:
    """Get the max output tokens for a model."""
    resolved = resolve_model_alias(model)
    return MAX_TOKENS_FOR_MODEL.get(resolved, DEFAULT_MAX_TOKENS)


class ProviderClient:
    """Unified provider client that dispatches to the correct backend.

    Maps to: rust/crates/api/src/client.rs::ProviderClient
    """

    def __init__(
        self,
        kind: ProviderKind,
        anthropic: AnthropicClient | None = None,
        openai_compat: OpenAiCompatClient | None = None,
        ollama: OllamaClient | None = None,
    ) -> None:
        self._kind = kind
        self._anthropic = anthropic
        self._openai_compat = openai_compat
        self._ollama = ollama

    @classmethod
    def from_model(
        cls,
        model: str,
        auth: AuthCredentials | None = None,
    ) -> ProviderClient:
        """Create a provider client based on the model name."""
        resolved = resolve_model_alias(model)
        kind = detect_provider_kind(resolved)

        if kind == ProviderKind.ANTHROPIC:
            if auth is not None:
                client = AnthropicClient(auth=auth)
            else:
                client = AnthropicClient.from_env()
            return cls(kind=kind, anthropic=client)

        if kind == ProviderKind.XAI:
            client = OpenAiCompatClient.from_env(OpenAiCompatConfig.xai())
            return cls(kind=kind, openai_compat=client)

        if kind == ProviderKind.OPENAI:
            client = OpenAiCompatClient.from_env(OpenAiCompatConfig.openai())
            return cls(kind=kind, openai_compat=client)

        if kind == ProviderKind.OLLAMA:
            ollama_client = OllamaClient.from_env(model=resolved)
            return cls(kind=kind, ollama=ollama_client)

        raise ApiError(f"Provider {kind.value} not yet implemented")

    @property
    def provider_kind(self) -> ProviderKind:
        return self._kind

    async def send_message(self, request: MessageRequest) -> MessageResponse:
        """Send a non-streaming message request."""
        if self._anthropic is not None:
            return await self._anthropic.send_message(request)
        if self._openai_compat is not None:
            return await self._openai_compat.send_message(request)
        if self._ollama is not None:
            return await self._ollama.send_message(request)
        raise ApiError("No provider client configured")

    async def stream_message(
        self, request: MessageRequest
    ) -> AsyncIterator[StreamEvent]:
        """Send a streaming request and yield events."""
        if self._anthropic is not None:
            async for event in self._anthropic.stream_message(request):
                yield event
            return
        if self._openai_compat is not None:
            async for event in self._openai_compat.stream_message(request):
                yield event
            return
        if self._ollama is not None:
            async for event in self._ollama.stream_message(request):
                yield event
            return
        raise ApiError("No provider client configured")

    async def close(self) -> None:
        """Close underlying HTTP clients."""
        if self._anthropic is not None:
            await self._anthropic.close()
        if self._openai_compat is not None:
            await self._openai_compat.close()
        if self._ollama is not None:
            await self._ollama.close()
