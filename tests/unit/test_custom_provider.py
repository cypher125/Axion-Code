"""Custom OpenAI-compatible provider (AXION_COMPAT_* env vars)."""

from __future__ import annotations

import pytest

from axion.api.client import (
    DEFAULT_CUSTOM_MAX_TOKENS,
    ProviderKind,
    custom_models,
    detect_provider_kind,
    is_custom_model,
    max_tokens_for_model,
)
from axion.api.error import ApiError
from axion.api.openai_compat import (
    OpenAiCompatClient,
    OpenAiCompatConfig,
    _build_chat_completion_request,
    _read_base_url,
)
from axion.api.types import InputMessage, MessageRequest, TextInputBlock


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("AXION_COMPAT_BASE_URL", "AXION_COMPAT_API_KEY", "AXION_COMPAT_MODELS", "AXION_COMPAT_MAX_TOKENS"):
        monkeypatch.delenv(key, raising=False)


def test_default_custom_model_is_rex():
    assert custom_models() == ("rex",)
    assert is_custom_model("rex") and is_custom_model("REX ")
    assert not is_custom_model("gpt-4o")


def test_models_list_from_env(monkeypatch):
    monkeypatch.setenv("AXION_COMPAT_MODELS", "rex, qwen-local ,")
    assert custom_models() == ("rex", "qwen-local")
    assert detect_provider_kind("qwen-local") == ProviderKind.CUSTOM


def test_custom_wins_over_prefix_detection(monkeypatch):
    monkeypatch.setenv("AXION_COMPAT_MODELS", "gpt-4o")
    assert detect_provider_kind("gpt-4o") == ProviderKind.CUSTOM
    monkeypatch.delenv("AXION_COMPAT_MODELS")
    assert detect_provider_kind("gpt-4o") == ProviderKind.OPENAI
    assert detect_provider_kind("rex") == ProviderKind.CUSTOM
    assert detect_provider_kind("claude-sonnet-4-6") == ProviderKind.ANTHROPIC


def test_max_tokens_for_custom_model(monkeypatch):
    assert max_tokens_for_model("rex") == DEFAULT_CUSTOM_MAX_TOKENS
    monkeypatch.setenv("AXION_COMPAT_MAX_TOKENS", "2048")
    assert max_tokens_for_model("rex") == 2048
    monkeypatch.setenv("AXION_COMPAT_MAX_TOKENS", "nope")
    assert max_tokens_for_model("rex") == DEFAULT_CUSTOM_MAX_TOKENS


def test_base_url_required():
    with pytest.raises(ApiError):
        _read_base_url(OpenAiCompatConfig.custom())


def test_client_from_env(monkeypatch):
    monkeypatch.setenv("AXION_COMPAT_BASE_URL", "https://example.test/v1/")
    monkeypatch.setenv("AXION_COMPAT_API_KEY", "k")
    client = OpenAiCompatClient.from_env(OpenAiCompatConfig.custom())
    assert client._base_url == "https://example.test/v1/"
    assert client.config.provider_name == "Custom"


def test_stream_usage_requested_for_custom():
    req = MessageRequest(
        model="rex",
        max_tokens=64,
        messages=[InputMessage(role="user", content=[TextInputBlock(text="hi")])],
        stream=True,
    )
    body = _build_chat_completion_request(req, OpenAiCompatConfig.custom())
    assert body["stream_options"] == {"include_usage": True}
    assert body["max_tokens"] == 64 and body["model"] == "rex"


def test_append_system_prompt_file(tmp_path):
    """AXION_APPEND_SYSTEM_PROMPT_FILE adds a trailing section without dropping built-ins."""
    from axion.runtime.prompt import SystemPromptBuilder

    identity = tmp_path / "identity.md"
    identity.write_text("# Identity: Rex\nYou are Rex.", encoding="utf-8")

    base = SystemPromptBuilder.for_cwd(tmp_path).render()
    extra = identity.read_text(encoding="utf-8").strip()
    appended = SystemPromptBuilder.for_cwd(tmp_path).append_section(extra).render()

    assert "You are Rex." in appended
    assert "You are Rex." not in base
    assert appended.rstrip().endswith("You are Rex.")
    # Built-in sections survive
    assert "# Using your tools" in appended and "# Using your tools" in base


def test_persona_switch_swaps_identity_block(tmp_path, monkeypatch):
    """/persona swaps the active identity in the live system prompt, preserving the base prompt."""
    import asyncio
    from types import SimpleNamespace

    from axion.cli.main import _handle_slash_command, _load_personas

    normal = tmp_path / "normal.md"
    dark = tmp_path / "dark.md"
    normal.write_text("You are Rex, a professional engineer.", encoding="utf-8")
    dark.write_text("You are Rex, a ruthless offensive-security operator.", encoding="utf-8")
    monkeypatch.setenv("AXION_PERSONAS", f"normal={normal};dark={dark}")

    personas = _load_personas()
    assert set(personas) == {"normal", "dark"}

    base = "# Built-in tool and permission rules\n\n"
    runtime = SimpleNamespace(system_prompt=base + personas["normal"])

    async def run(cmd: str) -> str:
        return await _handle_slash_command(cmd, runtime, None, None, None) or ""  # type: ignore[arg-type]

    msg = asyncio.run(run("/persona dark"))
    assert "dark" in msg
    assert personas["dark"] in runtime.system_prompt
    assert personas["normal"] not in runtime.system_prompt
    assert base.strip() in runtime.system_prompt  # base survived the swap

    asyncio.run(run("/persona normal"))
    assert personas["normal"] in runtime.system_prompt
    assert personas["dark"] not in runtime.system_prompt

    assert "Unknown persona" in asyncio.run(run("/persona nope"))
    assert "Already using" in asyncio.run(run("/persona normal"))


def test_cold_start_redirect_is_waited_out(monkeypatch):
    """A 303 from a scaled-to-zero container (Modal cold start) is waited out and retried, so the
    first request after idle succeeds instead of failing with 'API error 303'."""
    import asyncio

    import httpx

    from axion.api import openai_compat as oc
    from axion.api.types import InputMessage, MessageRequest, TextInputBlock

    monkeypatch.setattr(oc, "COLD_START_POLL_S", 0.01)
    monkeypatch.setattr(oc, "COLD_START_MAX_WAIT_S", 5.0)

    calls = {"n": 0}
    sse = b'data: {"choices":[{"delta":{"content":"hi"}}]}\n\ndata: [DONE]\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(303, text="See Other")  # container still booting
        return httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})

    client = oc.OpenAiCompatClient("k", oc.OpenAiCompatConfig.custom(), base_url="http://x")
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    req = MessageRequest(
        model="rex", max_tokens=8,
        messages=[InputMessage(role="user", content=[TextInputBlock(text="hi")])], stream=True,
    )

    async def run() -> bytes:
        chunks = []
        async for c in client._stream_raw_bytes(req):
            chunks.append(c)
        return b"".join(chunks)

    out = asyncio.new_event_loop().run_until_complete(run())
    assert calls["n"] == 3  # two 303s waited out, third succeeded
    assert b"hi" in out


def test_streamed_usage_surfaces_input_tokens():
    """OpenAI-compat streams usage in the trailing chunk; it must reach the final MessageDeltaEvent,
    otherwise input_tokens stays 0 and auto-compaction never fires (the overflow root cause)."""
    from axion.api.openai_compat import _StreamState
    from axion.api.types import MessageDeltaEvent

    state = _StreamState(model="rex")
    events = []
    events += state.ingest_chunk({"id": "1", "model": "rex", "choices": [{"delta": {"content": "hi"}}]})
    # trailing usage-only chunk, as vLLM/OpenAI send with stream_options include_usage
    events += state.ingest_chunk({"id": "1", "choices": [], "usage": {"prompt_tokens": 1234, "completion_tokens": 7}})
    events += state.finish()

    deltas = [e for e in events if isinstance(e, MessageDeltaEvent)]
    assert deltas, "no MessageDeltaEvent emitted"
    assert deltas[-1].usage.input_tokens == 1234
    assert deltas[-1].usage.output_tokens == 7
