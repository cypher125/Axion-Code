# Axion-Code

A Python CLI agent harness — a full port of [Claw Code](https://github.com/anthropics/claw-code) (Rust) which itself is a clone of Claude Code.

## What is this?

Axion-Code is an autonomous AI coding assistant that runs in your terminal. It connects to Anthropic's Claude API (or OpenAI-compatible APIs) and can read files, write code, execute commands, and manage complex software engineering tasks.

## Quick Start

```bash
# Install
cd python
pip install -e ".[dev]"

# Set your API key
export ANTHROPIC_API_KEY=sk-ant-...

# Interactive REPL
claw

# One-shot prompt
claw -p "Explain this codebase"

# Health check
claw doctor
```

## Architecture

9 packages mirroring the original Rust crate structure:

| Package | Purpose |
|---|---|
| `claw/api/` | Anthropic + OpenAI API clients with SSE streaming |
| `claw/runtime/` | Core engine — sessions, conversation loop, permissions, hooks, MCP, OAuth |
| `claw/cli/` | Terminal UI — REPL, markdown rendering, spinner, input completion |
| `claw/tools/` | Tool registry and execution (Bash, Read, Write, Edit, Glob, Grep) |
| `claw/commands/` | 60+ slash commands with fuzzy suggestions |
| `claw/plugins/` | Plugin system with manifest validation and lifecycle |
| `claw/telemetry/` | Session tracing and analytics |
| `claw/compat_harness/` | Upstream TypeScript manifest extraction |
| `tests/` | 116 unit tests + mock Anthropic server |

## Stats

- **87 Python files**
- **14,403 lines of code**
- **116 tests** (all passing)
- Python 3.11+ required

## Key Features

- Anthropic Claude + OpenAI/xAI provider support
- SSE streaming with markdown rendering
- Interactive REPL with slash commands and tab completion
- Tool system: Bash, Read, Write, Edit, Glob, Grep, WebSearch, WebFetch
- 3-layer config merge (user → project → local)
- Permission system (read-only / workspace-write / full-access)
- Hook system (pre/post tool execution)
- Plugin lifecycle (install/enable/disable/uninstall)
- MCP server management (JSON-RPC over stdio)
- OAuth PKCE flow with browser launch
- Session persistence and resume
- Token usage tracking and cost estimation
- LSP client integration
- Worker state machine and task registry

## License

MIT
