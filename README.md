# Axion-Code

[![CI](https://github.com/cypher125/Axion-Code/actions/workflows/ci.yml/badge.svg)](https://github.com/cypher125/Axion-Code/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](https://opensource.org/licenses/MIT)

An autonomous AI coding assistant that runs in your terminal. Axion connects to Claude, GPT, or any OpenAI-compatible API and can read your codebase, write code, run commands, manage files, search the web, and handle complex multi-step engineering tasks — all from a single prompt.

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

### Supported Providers

| Provider | Models | Env Variable |
|---|---|---|
| **Anthropic** | Claude Opus, Sonnet, Haiku | `ANTHROPIC_API_KEY` |
| **OpenAI** | GPT-4o, o1, o3 | `OPENAI_API_KEY` |
| **xAI** | Grok-2 | `XAI_API_KEY` |

```bash
# Use OpenAI
export OPENAI_API_KEY=sk-...
axion -m gpt-4o -p "Refactor this function"

# Use xAI
export XAI_API_KEY=xai-...
axion -m grok-2 -p "Explain this code"
```

## What Can It Do?

### Tools (12 built-in)

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

### Slash Commands (60+)

```
/help          Show all commands
/model opus    Switch model
/cost          Show token usage and costs
/compact       Compress conversation history
/status        Session info, git branch, token count
/config        Show loaded configuration sources
/mcp list      List connected MCP servers
/plugins list  List installed plugins
/skills list   List available skills
/agents list   List available agents
/doctor        Run health checks
/export        Export transcript to file
/session list  List saved sessions
/resume latest Resume last session
/login         Authenticate via OAuth
```

## Architecture

```
axion/
  api/           Anthropic + OpenAI clients, SSE streaming, retry, prompt caching
  cli/           REPL, markdown renderer, spinner, input completion, key bindings
  runtime/       Core engine:
    conversation   Model loop with hooks, auto-compaction, session tracing
    session        JSONL persistence with rotation
    permissions    Mode-based access control with decision caching
    config         3-layer merge (user < project < local)
    hooks          Pre/post tool execution with subprocess hooks
    mcp/           MCP server manager (stdio, SSE, HTTP, WebSocket, SDK)
    oauth          PKCE flow, browser launch, token refresh
    prompt         System prompt builder (41K chars, CLAUDE.md ancestor walking)
    memory         Persistent user/project/feedback entries
    git            Status, log, diff, commit, branch, stash
    skills         Load .md skill files with YAML frontmatter
    compact        Heuristic + model-based intelligent compaction
    lsp            LSP JSON-RPC client (hover, definition, completion)
    tasks          Task registry with team assignment and cron scheduling
    workers        Worker state machine with trust gate and prompt delivery
    policy_engine  Condition combinators, chained actions for git lane policies
    recovery       Failure recipes with async retry and escalation
  tools/         Tool registry, execution, deferred schema loading (ToolSearch)
  commands/      60+ slash commands with argument parsing and fuzzy suggestions
  plugins/       Plugin manifest, validation, lifecycle, persistence
  telemetry/     Session tracing, JSONL/memory sinks, analytics events
  compat_harness/ Upstream manifest extraction
```

## Configuration

Axion merges configuration from multiple sources (later overrides earlier):

1. **User**: `~/.claude/settings.json`
2. **Project**: `.claude.json` in repo root
3. **Local**: `.claude/settings.json` (gitignored)
4. **Local override**: `.claude/settings.local.json`
5. **Environment**: `ANTHROPIC_API_KEY`, `CLAUDE_MODEL`, etc.

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

Axion walks up the directory tree and includes all `CLAUDE.md` files it finds, so monorepos with nested instruction files work automatically.

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

Plugins can provide tools, commands, and hooks. See the plugin manifest format:

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
// .claude.json
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

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests (163 tests)
pytest tests/ -v

# Lint
ruff check axion/ tests/

# Type check
mypy axion/
```

### CI/CD

GitHub Actions runs on every push and PR:
- Tests on Python 3.11, 3.12, 3.13 across Linux, Windows, macOS
- Ruff linting and format checks
- CLI smoke tests

## Stats

| Metric | Value |
|---|---|
| Python files | 98 |
| Lines of code | 16,896 |
| Unit tests | 163 |
| Test coverage | All passing |
| Min Python | 3.11 |

## Author

**Cyrus** — [osawayecyrus@gmail.com](mailto:osawayecyrus@gmail.com) — [@cypher125](https://github.com/cypher125)

## License

MIT
