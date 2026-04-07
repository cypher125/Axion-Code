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
# 1. Install
pip install axion-code

# 2. Log in (one time — saves your key permanently)
axion login

# 3. Start coding
axion
```

That's it. No environment variables, no `.env` files. Your API key is saved to `~/.axion/credentials/` and works across all terminal sessions.

```bash
# One-shot prompt
axion -p "Find and fix the bug in auth.py"

# Use a specific model
axion -m opus

# Set a cost budget
axion --budget 1.00

# Permission mode (asks before dangerous ops)
axion --permission-mode prompt

# Resume last session
axion --resume latest

# Health check
axion doctor

# Log out (removes saved key)
axion logout
```

## Supported Providers

| Provider | Models | Login | Free? |
|---|---|---|---|
| **Anthropic** | Claude Opus, Sonnet, Haiku | `axion login` | No |
| **OpenAI** | GPT-4o, o1, o3 | `axion login --provider openai` | No |
| **xAI** | Grok-2 | `axion login --provider xai` | No |
| **Ollama** | Llama, Mistral, DeepSeek, Phi, Gemma, Qwen, CodeLlama | No login needed | Yes |

```bash
# Anthropic (default)
axion login
axion -p "Explain this codebase"

# OpenAI
axion login --provider openai
axion -m gpt-4o -p "Refactor this function"

# xAI
axion login --provider xai
axion -m grok-2 -p "Write tests for this module"

# Local models via Ollama (free, no login, no internet)
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
| **Read** | Read files with line ranges, binary detection, image/PDF support |
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
/diff          Show git changes with syntax highlighting
/plan <task>   Enter plan mode (read-only exploration + design)
/plan execute  Approve plan and start implementing
/plan exit     Cancel plan mode
```

### Real-Time Tool Display

When the AI uses tools (reading files, running commands, searching), you see it happening live:

```
╭─ Bash ─────────────────────────────────────────────────╮
│  command: git status --short
╰────────────────────────────────────────────────────────╯
✓ Bash
  ## main
  M  src/auth.py

╭─ Edit ─────────────────────────────────────────────────╮
│  file_path: src/auth.py
│  old_string: 'return None'
│  new_string: 'return token'
╰────────────────────────────────────────────────────────╯
✓ Edit
  Replaced 1 occurrence(s) in src/auth.py
```

Tool calls display **before** execution, results display **after** — you always know what the AI is doing.

### Interactive Permission Prompting

When using `--permission-mode prompt`, dangerous operations require your approval:

```
Permission required
  Tool: Bash
  Mode: prompt → needs workspace-write
  Input: {"command": "rm -rf /tmp/old"}

Allow? [y/N/a(lways)]: a
Allowed (always for this tool).
```

Three choices: `y` (allow once), `a` (allow always — remembered for this tool), `N` (deny). Permission decisions are cached so you won't be asked again for the same tool.

### Session Persistence & Resume

Every conversation is automatically saved. Manage multiple sessions:

```bash
# Resume the last session
axion --resume latest

# Resume by session ID (or partial ID)
axion --resume abc123

# Inside the REPL:
/session list           # List all saved sessions
/session switch abc123  # Switch to a different session
/session new            # Start a fresh session (saves current)
/session fork feature   # Fork current session with a name
/session delete abc123  # Remove an old session
/session show           # Show current session info
```

Sessions are stored as JSONL files in `.axion/sessions/` with automatic rotation at 256KB.

### Streaming Markdown Rendering

Responses are rendered as markdown in real-time — headings get colored, code blocks get syntax highlighted, and links are formatted. The renderer buffers text until safe boundaries (outside code fences) before rendering, so code blocks are never split mid-render.

### Error Recovery

Axion handles errors gracefully without crashing the REPL:
- **Context window exceeded**: Shows token usage percentage, suggests `/compact` or `/clear`
- **Authentication errors**: Suggests checking API key or running `/login`
- **Connection errors**: Suggests checking internet connection
- **Interrupted turns** (Ctrl+C): Resets cleanly, ready for next prompt

### Prompt Caching

System prompts are automatically cached using Anthropic's prompt caching API (`cache_control: ephemeral`), reducing token costs on repeated turns by avoiding re-processing the 41K character system prompt.

### Token Preflight Check

Before every API call, Axion estimates the token count and checks it against the model's context window (200K for Claude). If the request would exceed the limit, it raises a clear error before wasting an API call.

### Extended Thinking Display

When using Claude Opus with extended thinking, Axion shows a collapsed thinking indicator instead of dumping raw thinking text:

```
💭 Thinking...
```

The thinking content is captured internally but kept out of the output to keep responses clean.

### Image & PDF Reading

The Read tool automatically detects file types:
- **Images** (`.png`, `.jpg`, `.gif`, `.webp`, `.svg`): Returns base64-encoded content with metadata for the model to interpret
- **PDFs**: Tries `pdftotext` for text extraction, falls back to metadata if unavailable

### Syntax-Highlighted Diffs

The `/diff` command renders git changes with full syntax highlighting using the monokai theme, showing staged and unstaged changes separately:

```bash
/diff    # Shows colorized diff in the terminal
```

### Cost Budget Limits

Set a maximum spend per session to avoid surprise bills:

```bash
# Limit session to $1.00
axion --budget 1.00

# The AI will stop when the budget is reached
# Cost budget exceeded: $1.0234 >= $1.0000 budget.
# Use /cost to see breakdown or increase the budget.
```

Budgets are checked after every API call. Use `/cost` anytime to see your running total.

### Plan Mode

Design before coding. Plan mode blocks all write tools and lets the AI explore first:

```
axion> /plan Add JWT authentication to the API

📋 Plan mode ACTIVE
  Only read-only tools allowed (Read, Glob, Grep, WebSearch).
  Write/Edit/Bash are blocked until you approve.

  Task: Add JWT authentication to the API

axion[plan]> go ahead, explore the codebase and design a plan

[AI reads files, searches code, explores architecture...]

## Plan: Add JWT Authentication
1. Create auth/ module with token generation
2. Add middleware to validate tokens on protected routes
3. Create login endpoint
4. Add tests

### Files to modify:
- src/main.py
- src/models.py

Ready to implement. Type /plan execute to proceed.

axion[plan]> /plan execute

Plan approved! Exiting plan mode.
Write tools are now available. Send your next message to start implementing.

axion> implement the plan
```

The prompt changes to `axion[plan]>` so you always know when plan mode is active.

### Conversation Export

Export any session to a clean, readable markdown file:

```bash
/export                    # Saves to transcript-<session_id>.md
/export my-project.md      # Custom filename
```

The export includes numbered turns, collapsible tool use/result blocks (`<details>`), pretty-printed JSON, per-message token costs, and session metadata.

### Cron Scheduling

Schedule recurring tasks with standard cron expressions:

```python
# From the task/cron registries:
cron_registry.create("*/5 * * * *", TaskPacket(objective="Run health check", scope="all"))
cron_registry.create("0 9 * * 1-5", TaskPacket(objective="Daily standup summary", scope="src/"))
```

The `CronScheduler` runs as an async background loop, checking enabled entries every minute and triggering tasks via the `TaskRegistry`. Supports `*`, `*/N`, ranges (`1-5`), and comma lists (`0,15,30,45`).

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
                   Real-time tool use/result callbacks for live display
    session        JSONL persistence with rotation, resume by ID/latest
    permissions    Interactive [y/N/a] prompting, decision caching, persistence
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

### Authentication

```bash
axion login                      # Save Anthropic API key
axion login --provider openai    # Save OpenAI key
axion login --provider xai       # Save xAI key
axion logout                     # Remove all saved keys
```

Each provider shows its own signup URL and supported models:

```
$ axion login --provider openai

Axion Code Login

Provider: OpenAI (GPT)
Models: gpt-4o, o1, o3

Enter your API key:
  Get one at: https://platform.openai.com/api-keys

API key: sk-xxxxxxxx
Key saved! (sk-xxxxxx...xxxx)
You're ready to go! Run axion -m gpt-4o to start.
```

Keys are saved to `~/.axion/credentials/` with restricted file permissions. No environment variables needed — though env vars still work if you prefer them.

### Config File Hierarchy

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
| Python files | 102 |
| Lines of code | 18,184 |
| Unit tests | 166 |
| Integration tests | 7 (mock server) |
| Providers | 4 (Anthropic, OpenAI, xAI, Ollama) |
| Built-in tools | 13 |
| Slash commands | 60+ |
| CI matrix | 9 jobs (3 OS x 3 Python) |
| Min Python | 3.11 |

## Author

**Cyrus** — [osawayecyrus@gmail.com](mailto:osawayecyrus@gmail.com) — [@cypher125](https://github.com/cypher125)

## License

MIT
