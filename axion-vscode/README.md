# Axion Code — VS Code Extension

AI coding assistant inside VS Code. Use Claude, GPT, Grok, or local models to read, write, and edit code without leaving your editor.

## Features

- **Chat panel** in the sidebar — ask questions, get code written
- **Right-click menu** — "Ask Axion", "Explain Code", "Fix Bug", "Generate Tests", "Review File"
- **@file references** — tag any file to add context to your prompt
- **Multi-model** — switch between Claude, GPT, Grok, Ollama mid-conversation
- **Tool display** — see file reads, edits, bash commands as they happen
- **Cost tracking** — token count and cost in the status bar
- **Keyboard shortcuts** — Ctrl+Shift+A to open chat, Ctrl+Shift+E to ask about selection

## Prerequisites

The Axion CLI must be installed:

```bash
pip install axion-code
axion login
```

## Settings

| Setting | Default | Description |
|---|---|---|
| `axion.model` | `sonnet` | Default AI model |
| `axion.permissionMode` | `prompt` | Tool permission mode |
| `axion.cliPath` | `axion` | Path to Axion CLI |
| `axion.budget` | `0` | Max cost budget (0 = unlimited) |

## Commands

| Command | Shortcut | Description |
|---|---|---|
| Axion: Open Chat | `Ctrl+Shift+A` | Open the chat panel |
| Axion: Ask About Selection | `Ctrl+Shift+E` | Ask about selected code |
| Axion: Review This File | — | Run code review on current file |
| Axion: Generate Tests | — | Generate tests for current file |
| Axion: Explain This Code | — | Explain selected code |
| Axion: Fix Bug in Selection | — | Fix a bug in selected code |
| Axion: Switch Model | — | Change AI model |
| Axion: Activate License | — | Enter license key |

## Development

```bash
cd axion-vscode
npm install
npm run compile
# Press F5 in VS Code to launch Extension Development Host
```

## Author

**Cyrus** — osawayecyrus@gmail.com
