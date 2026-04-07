# Axion-Code

An autonomous AI coding assistant that runs in your terminal. Connects to Anthropic's Claude API (or OpenAI-compatible APIs) to read files, write code, execute commands, and manage complex software engineering tasks.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Interactive REPL
axion

# One-shot prompt
axion -p "Explain this codebase"

# Health check
axion doctor
```

## Architecture

9 packages:

| Package | Purpose |
|---|---|
| `axion/api/` | Anthropic + OpenAI API clients with SSE streaming |
| `axion/runtime/` | Core engine — sessions, conversation loop, permissions, hooks, MCP, OAuth |
| `axion/cli/` | Terminal UI — REPL, markdown rendering, spinner, input completion |
| `axion/tools/` | Tool registry and execution (Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch) |
| `axion/commands/` | 60+ slash commands with fuzzy suggestions |
| `axion/plugins/` | Plugin system with manifest validation and lifecycle |
| `axion/telemetry/` | Session tracing and analytics |
| `axion/compat_harness/` | Upstream manifest extraction |
| `tests/` | 148 unit tests + mock Anthropic server |

## Stats

- **95 Python files**
- **16,000+ lines of code**
- **148 tests** (all passing)
- Python 3.11+ required

## Key Features

- Anthropic Claude + OpenAI/xAI provider support
- SSE streaming with markdown rendering
- Interactive REPL with slash commands and tab completion
- Full tool system: Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch, Agent, TodoWrite, NotebookEdit, Skill
- System prompt with CLAUDE.md ancestor walking (41K chars)
- 3-layer config merge (user → project → local)
- Permission system with persistence (read-only / workspace-write / full-access)
- Hook system (pre/post tool execution)
- Plugin lifecycle (install/enable/disable/uninstall)
- MCP server management (JSON-RPC over stdio, 6 transport types)
- OAuth PKCE flow with browser launch and token refresh
- Session persistence and resume
- Token preflight check and prompt caching
- Persistent memory system (user/feedback/project/reference)
- Git workflows (status, log, commit, branch, stash)
- Skill execution from .md files with YAML frontmatter
- Model-based intelligent session compaction
- LSP client integration
- Worker state machine and task registry with team/cron scheduling
- Policy engine with condition combinators

## Author

**Cyrus** — osawayecyrus@gmail.com

## License

MIT
