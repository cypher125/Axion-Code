"""Handler for the /models slash command.

Lists locally available Ollama models when an Ollama server is running.
"""

from __future__ import annotations

import asyncio

from axion.api.ollama import OllamaClient


def handle_models_command(args: str = "") -> str:
    """Handle /models -- list available Ollama models.

    Runs the async listing synchronously so the command handler can be
    invoked from a synchronous slash-command dispatch path.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Already inside an async context; create a task via a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(_list_models_sync).result(timeout=10)
        return result

    return asyncio.run(_list_models_async())


def _list_models_sync() -> str:
    return asyncio.run(_list_models_async())


async def _list_models_async() -> str:
    client = OllamaClient.from_env()

    if not await client.is_available():
        await client.close()
        return (
            "Ollama is not running.\n"
            "Start it with: ollama serve\n"
            f"Expected at: {client.base_url}"
        )

    try:
        models = await client.list_models()
    finally:
        await client.close()

    if not models:
        return "Ollama is running but no models are installed.\nPull one with: ollama pull llama3.1"

    lines = [f"Available Ollama models ({len(models)}):", ""]
    for m in models:
        size_mb = m.size / (1024 * 1024) if m.size else 0
        family = m.details.get("family", "")
        params = m.details.get("parameter_size", "")
        detail_parts: list[str] = []
        if params:
            detail_parts.append(params)
        if family:
            detail_parts.append(family)
        if size_mb > 0:
            detail_parts.append(f"{size_mb:.0f} MB")
        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        lines.append(f"  {m.name}{detail}")

    lines.append("")
    lines.append('Use a model with: /model <name>  or  --model "<name>"')
    return "\n".join(lines)
