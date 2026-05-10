# Axion-Code

[![PyPI version](https://img.shields.io/pypi/v/axion-code.svg?color=00d4aa)](https://pypi.org/project/axion-code/)
[![PyPI downloads](https://img.shields.io/pypi/dm/axion-code.svg?color=64ffda)](https://pypi.org/project/axion-code/)
[![Python 3.11+](https://img.shields.io/pypi/pyversions/axion-code.svg)](https://pypi.org/project/axion-code/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)
[![CI](https://github.com/cypher125/Axion-Code/actions/workflows/ci.yml/badge.svg)](https://github.com/cypher125/Axion-Code/actions/workflows/ci.yml)
[![GitHub stars](https://img.shields.io/github/stars/cypher125/Axion-Code.svg?style=social)](https://github.com/cypher125/Axion-Code/stargazers)

An autonomous AI coding assistant that runs in your terminal. Axion connects to Claude, GPT, Grok, OpenAI Codex, or any local model via Ollama and can read your codebase, write code, run commands, manage files, search the web, and handle complex multi-step engineering tasks — all from a single prompt.

**Use your existing subscription.** Bring your **Claude Pro/Max** plan or **ChatGPT Plus/Pro/Business** plan instead of paying per-token. Axion authenticates via OAuth with the same flows the official Claude Code and OpenAI Codex CLIs use, so requests are billed against your existing plan. API keys still work too — pick whichever fits your usage.

<p align="center">
  <img src="https://raw.githubusercontent.com/cypher125/Axion-Code/main/assets/screenshots/welcome.png" alt="Axion welcome screen with Pro/Max subscription badge" width="900">
</p>

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

| Provider | Models | API Key Login | Subscription Login |
|---|---|---|---|
| **Anthropic** | Claude Opus 4.7, Sonnet 4.6, Haiku 4.5 | `axion login` | `axion login --subscription` (Claude Pro/Max) |
| **OpenAI** | GPT-5, GPT-4o, o1, o3, o4-mini | `axion login --provider openai` | — |
| **OpenAI Codex** | gpt-5-codex, gpt-5-codex-mini (Responses API) | `axion login --provider openai` | `axion login --subscription --provider openai` (ChatGPT Plus/Pro/Business) |
| **xAI** | Grok-2, Grok-3 | `axion login --provider xai` | — |
| **Ollama** | Llama, Mistral, DeepSeek, Phi, Gemma, Qwen, CodeLlama | No login needed (free, local) | — |

```bash
# Anthropic — pick API key or Claude Pro/Max subscription
axion login                          # interactive: pick 1=subscription, 2=API key
axion login --subscription           # opens browser → claude.ai → paste code
axion -p "Explain this codebase"

# OpenAI Codex — agent-tuned coding model via the Responses API
axion login --provider openai                 # pay-per-token
axion login --subscription --provider openai  # ChatGPT Plus/Pro/Business
axion -m codex -p "Refactor this function"

# OpenAI Chat Completions
axion -m gpt-5 -p "Write tests for this module"

# xAI
axion login --provider xai
axion -m grok-2 -p "Review this code"

# Local models via Ollama (free, no login, no internet)
ollama pull llama3.1
axion -m llama3.1 -p "Refactor this"

# List available models across all configured providers
axion models       # or: /models inside the REPL
```

Switching models mid-conversation is autocomplete-driven — type `/model ` and pick from the dropdown:

<p align="center">
  <img src="https://raw.githubusercontent.com/cypher125/Axion-Code/main/assets/screenshots/models.png" alt="Axion /model autocomplete dropdown showing all configured providers" width="900">
</p>

### Subscription vs API Key

| | Subscription (Pro/Max, ChatGPT Plus+) | API Key |
|---|---|---|
| **Cost** | Flat monthly fee | Pay per token |
| **Rate limits** | Plan-based 5-hour rolling window | Per-org TPM/RPM |
| **Auth** | OAuth (browser) | API key string |
| **Storage** | `~/.axion/credentials/anthropic-oauth.json` (or `openai-oauth.json`) | `~/.axion/credentials/anthropic.key` (etc.) |
| **Best for** | Heavy daily use | Occasional / programmatic use |
| **Required model** | Any Claude model / Codex models | Any |

Switch between modes mid-session with `/auth-mode subscription` or `/auth-mode api`. The provider client rebuilds in place — no restart needed.

The welcome screen and bottom toolbar always show which mode is active:

```
claude-sonnet-4-6 · Pro/Max          ← Anthropic subscription
gpt-5-codex · ChatGPT                ← OpenAI subscription
gpt-5 · API                          ← API key (pay-per-token)
qwen2:7b · local                     ← Ollama (free, on-device)
```

Run `/auth-mode status` inside the REPL to see exactly what's configured for both providers at once:

<p align="center">
  <img src="https://raw.githubusercontent.com/cypher125/Axion-Code/main/assets/screenshots/auth-status.png" alt="/auth-mode status showing both Anthropic Pro/Max subscription and OpenAI account configuration" width="900">
</p>

When the subscription is rate-limited, the error includes the exact retry time parsed from the `anthropic-ratelimit-*-reset` headers:

```
Rate limit hit — retry at 14:32 (in 18 min)
Your Claude Pro/Max plan limits messages per 5-hour window:
  • Pro:  ~45 messages / 5h
  • Max:  ~225-900 messages / 5h (depending on tier)

Options while you wait:
  • Switch to API key billing: /auth-mode api
  • Use a different provider: /model gpt-5 or /model grok-2
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

### Slash Commands (45)

```
/help                  Show all commands
/model opus            Switch model mid-conversation
/models                List models across all configured providers (Anthropic, OpenAI, xAI, Ollama)
/cost                  Show token usage and costs
/compact               Compress conversation history (heuristic or model-based)
/status                Session info, git branch, token count
/config                Show loaded configuration sources
/mcp list              List connected MCP servers
/plugins list          List installed plugins
/skills list           List available skills
/agents list           List available agents
/doctor                Run health checks
/export                Export transcript to markdown
/session list          List saved sessions
/resume latest         Resume last session (replays full conversation)
/login                 Authenticate via OAuth
/logout                Clear stored credentials (API key + subscription)
/auth-mode             Show or switch auth (subscription / api / status)
/memory                View persistent memory entries
/diff                  Show git changes with syntax highlighting
/image                 Paste image from clipboard or file path (also works inline mid-prompt)
/plan <task>           Enter plan mode (read-only exploration + design)
/plan execute          Approve plan and start implementing
/plan exit             Cancel plan mode
```

### Real-Time Tool Display

When the AI uses tools (reading files, running commands, editing), you see it happening live in a compact, Claude Code-style inline format. Tool calls render as `● ToolName(args)` followed by a `└` summary line — no panels, no scrolling, just signal.

**Multi-step turn — write a file, then run it:**

<p align="center">
  <img src="https://raw.githubusercontent.com/cypher125/Axion-Code/main/assets/screenshots/inline-tools.png" alt="Axion writing fizzbuzz.py and running it inline, showing Write + Bash tool calls with line-numbered output" width="900">
</p>

**Edit shows a real line-numbered diff** — red background for removals, green for additions, anchored to the actual line in the file:

<p align="center">
  <img src="https://raw.githubusercontent.com/cypher125/Axion-Code/main/assets/screenshots/edit-diff.png" alt="Axion editing fizzbuzz.py with line-numbered red/green diff highlighting" width="900">
</p>

**Write shows the new content with line numbers** and a `+N lines (ctrl+o to expand)` truncation marker for files over 14 lines:

<p align="center">
  <img src="https://raw.githubusercontent.com/cypher125/Axion-Code/main/assets/screenshots/streaming-markdown.png" alt="Axion writing http_status_codes.md with full content preview and line numbers" width="900">
</p>

`Bash` shows a one-line status that updates live as stderr/stdout streams in (`⠋ Building project...` → `⠹ Generating static pages (3/6)...` → result), so long `npm install` / `cargo build` runs don't freeze the screen. `Ctrl+C` cancels just the running command, not the whole session.

### Image Input

Paste screenshots or attach image files directly to your prompts — works with any vision-capable model (Claude Opus/Sonnet/Haiku, GPT-4o, GPT-5, Codex):

```
# 1. Take a screenshot, then:
> /image what's wrong with this UI?

# 2. Or attach a file:
> /image ./error.png explain this stack trace

# 3. Inline anywhere in a message:
> this UI looks generic /image — make it look more like Stripe's checkout

# 4. Auto-detected from file paths in input:
> fix the bug shown in error.png
```

Supports `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp` up to 5MB. Images are base64-encoded and sent natively to both Anthropic (`source.type=base64`) and OpenAI (`image_url` data URL) — same wire format their APIs expect.

Example — pasted a landing-page screenshot from clipboard, asked for UI fixes:

<p align="center">
  <img src="https://raw.githubusercontent.com/cypher125/Axion-Code/main/assets/screenshots/image-input.png" alt="Axion analyzing a screenshot pasted via /image and returning structured UI feedback" width="900">
</p>

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

Every conversation is automatically saved. When you resume, Axion **replays the entire conversation** in the original Claude Code-style inline format — your past messages, the AI's responses (rendered as markdown), every tool call with its diff and output. It looks identical to scrolling up in the original session, so you can continue where you left off without context loss.

```bash
# Resume the last session (full replay)
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

### Compact System Prompt

The system prompt is intentionally kept small (~1,200 tokens) — about the same size as Claude Code's. We do not embed the full `git diff` or `settings.json` into every request the way some agents do; the model can run those itself with its tools when needed. On Anthropic, the prompt is wrapped with `cache_control: ephemeral` so even those tokens are billed at cache-read rates after the first turn.

Net effect: a "hello" turn to Claude Sonnet costs roughly ~2,000 input tokens including tool definitions, instead of the ~32,000 you'd get if everything were inlined. Subscription users get ~26x more sustained throughput out of the same Pro/Max bucket.

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
  api/           4 providers, 5 transport clients
    anthropic           Claude API: SSE streaming, retry, prompt caching, OAuth bearer support
    openai_compat       OpenAI/xAI Chat Completions client with streaming state machine
    openai_responses    OpenAI Responses API client for Codex (gpt-5-codex, gpt-5-codex-mini)
    ollama              Local model client (auto-detect llama/mistral/deepseek/phi/gemma/qwen)
    types               Shared types: MessageRequest, StreamEvent, ImageInputBlock, Usage
    sse                 Server-Sent Events parser
    error               Error hierarchy with retry classification
    client              ProviderClient factory with model-aware routing
  cli/           Terminal interface
    main                REPL loop, 45 slash commands, session management, image detection
    render              Streaming markdown renderer with safe-boundary buffering
    input               Tab completion, key bindings, bottom toolbar with auth badge
    tui                 Welcome screen, inline tool display, line-numbered diff renderer
  runtime/       Core engine
    conversation        Agentic loop: stream → tools (parallel Agent calls) → hooks → compact
    session             JSONL persistence with rotation, full conversation replay on resume
    permissions         Interactive [y/N/a] prompting, decision caching, persistence
    config              3-layer merge with 6 MCP transport types
    hooks               Pre/post/failure hooks via subprocess
    mcp/                Model Context Protocol (stdio, SSE, HTTP, WebSocket, SDK)
    oauth               PKCE flow with browser launch, callback server, token refresh
    claude_subscription Claude Pro/Max OAuth (paste-style, claude.ai endpoints)
    openai_subscription ChatGPT subscription OAuth (local-callback, auth.openai.com)
    image               Clipboard image grab (Win32/macOS/Linux), file loading, base64 encoding
    prompt              Compact system prompt builder (~1.2K tokens) with AXION.md walking
    bash                Live status spinner, stderr streaming, Ctrl+C cancellation
    memory              Persistent user/feedback/project/reference entries
    git                 Status, log, diff, commit, branch, stash
    skills              Load .md skill files with YAML frontmatter
    compact             Heuristic + model-based intelligent compaction
    lsp                 LSP JSON-RPC client (hover, definition, completion, symbols)
    tasks               Task registry with team assignment and cron scheduling
    workers             Worker state machine with trust gate and prompt delivery
    policy_engine       Condition combinators (And/Or/GreenAt), chained actions
    recovery            Failure recipes with async retry and escalation
  tools/         13 built-in tools + deferred schema loading (ToolSearch)
  commands/      45 slash commands with argument parsing and fuzzy suggestions
  plugins/       Plugin manifest validation, lifecycle execution, persistence
  telemetry/     Session tracing, JSONL/memory sinks, analytics events
  compat_harness/ Upstream manifest extraction
```

## Configuration

### Authentication

Two ways to authenticate, mix and match per provider:

```bash
# API key (pay-per-token)
axion login                      # Anthropic — interactive picker
axion login --provider openai    # OpenAI
axion login --provider xai       # xAI

# Subscription OAuth (use existing plan)
axion login --subscription                       # Claude Pro/Max
axion login --subscription --provider openai     # ChatGPT Plus/Pro/Business

# Logout
axion logout                                     # clears Anthropic creds (key + OAuth)
axion logout --provider openai                   # clears OpenAI creds
```

**Claude subscription** uses a paste-style flow (the same one Claude Code uses): `claude.ai` displays an authentication code on a success page, you paste it back into the terminal. No local server needed.

**ChatGPT subscription** uses a local-callback flow on port `1455` (the same one OpenAI's codex CLI uses): browser → `auth.openai.com` → automatic redirect back. Note that ChatGPT subscriptions only authorize the **Codex** models (Responses API). Free ChatGPT plans don't include Codex API access — Plus/Pro/Business do.

When you log in interactively without flags, Axion asks which path you want:

```
$ axion login

Axion Code Login

How do you want to use Claude?

  1. Subscription (Claude Pro/Max) — uses your $20-200/mo plan
       Best if you have a Claude subscription, no per-token billing
  2. API key (pay-per-token)
       Best for occasional use or if you don't have a subscription

Choose [1/2]: 1
```

Credentials are saved to `~/.axion/credentials/` (chmod 600). API keys are stored as plain `.key` files; OAuth tokens go in `*-oauth.json` with auto-refresh.

You can force API mode at runtime even when a subscription is saved:

```bash
AXION_AUTH_MODE=api axion       # one-off
# or inside the REPL:
/auth-mode api                  # rebuilds the provider client immediately
/auth-mode subscription         # switches back
/auth-mode status               # shows what's currently active for both providers
```

### Config File Hierarchy

Axion merges configuration from multiple sources (later overrides earlier):

1. **User**: `~/.axion/settings.json`
2. **Project**: `.axion.json` in repo root
3. **Local**: `.axion/settings.json` (gitignored)
4. **Local override**: `.axion/settings.local.json`
5. **Environment**: `ANTHROPIC_API_KEY`, `AXION_MODEL`, `OLLAMA_BASE_URL`, etc.

### AXION.md

Drop an `AXION.md` in your project root to give Axion context about your codebase:

```markdown
# AXION.md

## Project overview
This is a Django REST API for managing user accounts.

## Build & test
- `python manage.py test`
- `ruff check .`

## Code conventions
- Use type hints everywhere
- Prefer dataclasses over dicts
```

Axion walks up the directory tree and includes all `AXION.md` files it finds — monorepos with nested instruction files at different levels work automatically. Files are deduplicated by content hash and truncated to a 12,000 character budget.

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

## Terminal Theme

Axion looks best with a dark navy terminal. For the optimal look:

**Windows Terminal** — Add to your settings.json profiles:
```json
{
    "colorScheme": "One Half Dark",
    "background": "#0a192f",
    "font": { "face": "Cascadia Code", "size": 13 }
}
```

**VS Code Terminal** — Add to settings.json:
```json
{
    "terminal.integrated.fontFamily": "Cascadia Code",
    "workbench.colorCustomizations": {
        "terminal.background": "#0a192f"
    }
}
```

Axion uses a **cyan/teal accent** (#00d4aa) with **mint green** (#64ffda) for success and **coral red** (#ff6b6b) for errors.

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
| Python files | 111 |
| Lines of code | 23,216 |
| Unit tests | 166 |
| Integration tests | 7 (mock server) |
| Providers | 4 (Anthropic, OpenAI, xAI, Ollama) |
| API transports | 5 (Anthropic, OpenAI Chat Completions, OpenAI Responses, xAI, Ollama) |
| Auth modes | 4 (API key, Claude Pro/Max, ChatGPT Plus/Pro/Business, local) |
| Built-in tools | 13 |
| Slash commands | 47 |
| System prompt size | ~1,200 tokens (≈26x smaller than naive approach) |
| CI matrix | 9 jobs (3 OS x 3 Python) |
| Min Python | 3.11 |

## Author

**Cyrus** — [osawayecyrus@gmail.com](mailto:osawayecyrus@gmail.com) — [@cypher125](https://github.com/cypher125)

## Sponsoring

Axion is **free and open source** (MIT). It will always stay that way for individual developers — no per-seat licenses, no paid tiers gating features, no usage caps.

If Axion saves you time and you'd like to keep it healthy:

- **Star the repo** — visibility is the cheapest way to help
- **Sponsor** via [GitHub Sponsors](https://github.com/sponsors/cypher125) — covers maintenance time
- **Contribute** — issues, PRs, and custom slash commands all welcome
- **Tell people** — a tweet, a blog post, or a recommendation to a teammate goes a long way

For companies adopting Axion at scale, a hosted/team product is on the roadmap (shared sessions, audit logs, SSO). [Email me](mailto:osawayecyrus@gmail.com) if that's interesting and we can chat early-access.

## License

[MIT](LICENSE) — do whatever you want, no warranty, attribution appreciated.
