# Axion-Code

[![CI](https://github.com/cypher125/Axion-Code/actions/workflows/ci.yml/badge.svg)](https://github.com/cypher125/Axion-Code/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

An autonomous AI coding assistant that runs in your terminal. Axion connects to Claude, GPT, Grok, or any local model via Ollama and can read your codebase, write code, run commands, manage files, search the web, and handle complex multi-step engineering tasks — all from a single prompt.

---

## Installation

```bash
pip install axion-code

# Or install from source
git clone https://github.com/cypher125/Axion-Code.git
cd Axion-Code
pip install -e ".[dev]"
```

## Quick Start

```bash
# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Interactive REPL
axion

# One-shot prompt
axion -p "Find and fix the bug in auth.py"

# Use a specific model
axion -m opus

# Health check
axion doctor
```

## Supported Providers

| Provider | Models | Env Variable | Setup |
|---|---|---|---|
| **Anthropic** | Claude Opus, Sonnet, Haiku | `ANTHROPIC_API_KEY` | `export ANTHROPIC_API_KEY=sk-ant-...` |
| **OpenAI** | GPT-4o, o1, o3 | `OPENAI_API_KEY` | `export OPENAI_API_KEY=sk-...` |
| **xAI** | Grok-2 | `XAI_API_KEY` | `export XAI_API_KEY=xai-...` |
| **Ollama** | Llama, Mistral, DeepSeek, Phi, Gemma, Qwen, CodeLlama | None (local) | [Install Ollama](https://ollama.ai) |

```bash
# Anthropic (default)
axion -p "Explain this codebase"

# OpenAI
axion -m gpt-4o -p "Refactor this function"

# xAI
axion -m grok-2 -p "Write tests for this module"

# Local models via Ollama (no API key, no internet, free)
ollama pull llama3.1
axion -m llama3.1 -p "Review this code"

# List available local models
axion models
```

## What Can It Do?

### Tools (13 built-in)

| Tool | What it does |
|---|---|
| **Bash** | Execute shell commands with timeout, background mode, sandboxing |
| **Read** | Read files with line ranges, binary detection, size limits |
| **Write** | Create or update files with automatic patch generation |
| **Edit** | Find-and-replace in files with uniqueness validation |
| **Glob** | Search for files by pattern, sorted by modification time |
| **Grep** | Regex search across files with context lines, file type filtering |
| **WebSearch** | Search the web via DuckDuckGo (no API key needed) |
| **WebFetch** | Fetch any URL and return its content |
| **Agent** | Spawn sub-agents for parallel task execution |
| **TodoWrite** | Manage structured task lists for complex workflows |
| **NotebookEdit** | Edit Jupyter notebook cells (insert, replace, delete) |
| **Skill** | Load and execute skill templates from `.md` files |
| **ToolSearch** | Deferred tool schema loading — search and activate tools on demand |

All tools are automatically sent to the model with every request, so the AI can read files, write code, run commands, and search the web without any manual setup.

### Slash Commands (60+)

```
/help          Show all commands
/model opus    Switch model mid-conversation
/models        List available Ollama models
/cost          Show token usage and costs
/compact       Compress conversation history (heuristic or model-based)
/status        Session info, git branch, token count
/config        Show loaded configuration sources
/mcp list      List connected MCP servers
/plugins list  List installed plugins
/skills list   List available skills
/agents list   List available agents
/doctor        Run health checks
/export        Export transcript to markdown
/session list  List saved sessions
/resume latest Resume last session
/login         Authenticate via OAuth
/memory        View persistent memory entries
/diff          Show current git changes
```

### Streaming Markdown Rendering

Responses are rendered as markdown in real-time — headings get colored, code blocks get syntax highlighted, and links are formatted. The renderer buffers text until safe boundaries (outside code fences) before rendering, so code blocks are never split mid-render.

### Error Recovery

Axion handles errors gracefully without crashing the REPL:
- **Context window exceeded**: Shows token usage, suggests `/compact` or `/clear`
- **Authentication errors**: Suggests checking API key or running `/login`
- **Connection errors**: Suggests checking internet connection
- **Interrupted turns**: Resets cleanly, ready for next prompt

### Prompt Caching

System prompts are automatically cached using Anthropic's prompt caching API (`cache_control: ephemeral`), reducing token costs on repeated turns by avoiding re-processing the 41K character system prompt.

### Token Preflight Check

Before every API call, Axion estimates the token count and checks it against the model's context window (200K for Claude). If the request would exceed the limit, it raises a clear error before wasting an API call.

## Architecture

```
axion/
  api/           4 providers: Anthropic, OpenAI, xAI, Ollama
    anthropic      Claude API client with SSE streaming, retry, prompt caching
    openai_compat  OpenAI/xAI client with streaming state machine
    ollama         Local model client (auto-detect llama/mistral/deepseek/phi/gemma/qwen)
    types          Shared types: MessageRequest, StreamEvent, Usage, etc.
    sse            Server-Sent Events parser
    error          Error hierarchy with retry classification
  cli/           Terminal interface
    main           REPL loop, 60+ slash commands, session management
    render         Streaming markdown, box-drawing tool display, spinner
    input          Tab completion, key bindings, multiline input
  runtime/       Core engine (22 modules)
    conversation   Agentic loop: stream → tools → hooks → compact → loop
    session        JSONL persistence with rotation (256KB files)
    permissions    Mode-based access control with decision persistence
    config         3-layer merge with 6 MCP transport types
    hooks          Pre/post/failure hooks via subprocess
    mcp/           Model Context Protocol (stdio, SSE, HTTP, WebSocket, SDK)
    oauth          PKCE flow with browser launch, callback server, token refresh
    prompt         System prompt builder (41K chars, CLAUDE.md ancestor walking)
    memory         Persistent user/feedback/project/reference entries
    git            Status, log, diff, commit, branch, stash
    skills         Load .md skill files with YAML frontmatter
    compact        Heuristic + model-based intelligent compaction
    lsp            LSP JSON-RPC client (hover, definition, completion, symbols)
    tasks          Task registry with team assignment and cron scheduling
    workers        Worker state machine with trust gate and prompt delivery
    policy_engine  Condition combinators (And/Or/GreenAt), chained actions
    recovery       Failure recipes with async retry and escalation
  tools/         13 built-in tools + deferred schema loading (ToolSearch)
  commands/      60+ slash commands with argument parsing and fuzzy suggestions
  plugins/       Plugin manifest validation, lifecycle execution, persistence
  telemetry/     Session tracing, JSONL/memory sinks, analytics events
  compat_harness/ Upstream manifest extraction
```

## Configuration

Axion merges configuration from multiple sources (later overrides earlier):

1. **User**: `~/.claude/settings.json`
2. **Project**: `.claude.json` in repo root
3. **Local**: `.claude/settings.json` (gitignored)
4. **Local override**: `.claude/settings.local.json`
5. **Environment**: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, `OLLAMA_BASE_URL`, etc.

### CLAUDE.md

Drop a `CLAUDE.md` in your project root to give Axion context about your codebase:

```markdown
# CLAUDE.md

## Project overview
This is a Django REST API for managing user accounts.

## Build & test
- `python manage.py test`
- `ruff check .`

## Code conventions
- Use type hints everywhere
- Prefer dataclasses over dicts
```

Axion walks up the directory tree and includes all `CLAUDE.md` files it finds — monorepos with nested instruction files at different levels work automatically. Files are deduplicated by content hash and truncated to a 12,000 character budget.

## Plugin System

```bash
# List plugins
axion plugins list

# Install from directory
axion plugins install ./my-plugin

# Enable/disable
axion plugins enable my-plugin
axion plugins disable my-plugin
```

Plugins can provide tools, commands, and hooks. Manifests are validated for hook path existence, tool schema correctness, and lifecycle command availability.

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "hooks": {
    "preToolUse": ["./hooks/check.sh"],
    "postToolUse": ["./hooks/log.sh"]
  },
  "tools": [
    {
      "name": "MyCustomTool",
      "description": "Does something cool",
      "inputSchema": { "type": "object", "properties": {} }
    }
  ]
}
```

## MCP Servers

Axion supports the [Model Context Protocol](https://modelcontextprotocol.io/) for connecting to external tool servers:

```json
{
  "mcpServers": {
    "my-server": {
      "type": "stdio",
      "command": "node",
      "args": ["./mcp-server/index.js"]
    }
  }
}
```

Supports 6 transport types: stdio, SSE, HTTP, WebSocket, SDK, and managed proxy.

## Memory System

Axion has a persistent memory system that stores context across conversations:

```bash
# View memory entries
axion memory
```

Memory types: `user` (preferences), `feedback` (corrections), `project` (decisions), `reference` (external links). Entries are stored as `.md` files with YAML frontmatter in `~/.axion/memory/`.

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check axion/ tests/

# Type check
mypy axion/
```

### CI/CD

GitHub Actions runs on every push and PR:
- Tests on **Python 3.11, 3.12, 3.13** across **Linux, Windows, macOS** (9 matrix jobs)
- Ruff linting
- CLI smoke tests (`axion --version`, `axion doctor`)

## Stats

| Metric | Value |
|---|---|
| Python files | 100 |
| Lines of code | 17,564 |
| Unit tests | 156 |
| Integration tests | 7 (mock server) |
| Providers | 4 (Anthropic, OpenAI, xAI, Ollama) |
| Built-in tools | 13 |
| Slash commands | 60+ |
| Min Python | 3.11 |

## Author

**Cyrus** — [osawayecyrus@gmail.com](mailto:osawayecyrus@gmail.com) — [@cypher125](https://github.com/cypher125)

## License

MIT
