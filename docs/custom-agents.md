# Custom sub-agent roles

Define your own agent roles as markdown files in any of:

- `.axion/agents/*.md` (per project)
- `.claude/agents/*.md` (per project, compatibility)
- `~/.axion/agents/*.md` (global, all projects)

Each file is frontmatter + a system prompt body:

```markdown
---
name: reviewer
description: Reviews a diff or file for correctness and security.
mode: read-only          # optional: read-only | workspace-write | danger-full-access
---
You are a strict, skeptical code reviewer. Read the target thoroughly and report only real bugs,
missed edge cases, and security issues, with file:line where visible. Never modify anything.
```

Then the model (or you) can launch it with the Agent tool using `subagent_type: "reviewer"`. The child
runs with that role prompt, at the `mode` you set (never above the parent's permission), and — like the
built-in `explore` / `plan` / `general` roles — several can run in parallel in one turn.

Notes:
- `mode` defaults to inheriting the parent's permission mode if omitted or invalid.
- The role prompt replaces the parent's identity for that worker; the operator's persistent memory is not
  loaded into sub-agents.
