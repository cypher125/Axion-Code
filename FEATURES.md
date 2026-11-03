# Axion feature build — Claude-Code-parity additions

The high-value features Claude Code had that Axion lacked. All harness-side; suite 197 passing (was 193).

## 1. Interruptibility & steering — DONE
Ctrl-C stops the model CLEANLY mid-turn and keeps the partial reply; you can continue or redirect.
`_interruptible()` races each stream event against an interrupt Event (stops even mid-generation) and
acloses the stream; `run_turn` marks `TurnSummary.interrupted` and saves partial text as a clean message;
REPL: first Ctrl-C = clean stop, second = force cancel. Test: `test_interrupt_preserves_partial_text`.

## 2. Real typed subagents + parallelism — DONE (extended)
`AGENT_TYPES`: explore/plan (read-only, role-prompted) and general (inherits parent mode). The Agent tool
takes `subagent_type`, spawns the child at ≤ parent permission with a role prompt, and cleans up.
Multiple Agent calls in one turn run in parallel. Tests: `test_agent_typed_roles_defined`.
Extended 2026-09-16 (suite 200):
- Live per-agent progress: the child emits `PROGRESS` lines on stderr (when AXION_EMIT_PROGRESS=1) for each
  tool it runs; the parent streams them prefixed with the agent label. You now see each agent working.
- Per-agent tokens/cost: the parent parses the child's JSON usage and prints `[label] done — N tokens, $X`.
- User-defined agent types: `load_custom_agent_types()` reads `.axion/agents/*.md` (+ `.claude/agents/*.md`,
  `~/.axion/agents`) — frontmatter (name/description/mode) + body prompt — merged with the built-ins. The
  subagent_type field is now a free string so custom role names work. Docs: docs/custom-agents.md.
  Tests: `test_custom_agent_types_loaded`, `test_subagent_progress_and_types_merge`.

## 3. Verification / self-review — DONE
`/review` sends the working tree's uncommitted git diff to the model and asks for a rigorous correctness
review (bugs, edge cases, security), returning concrete issues. User-triggered (no per-turn cost).

## 4. Diff review for edits — DONE
Edit / Write / MultiEdit now return a compact unified diff of what changed, so every file change is visible.
`format_unified_diff()` in file_ops. Test: `test_edit_shows_diff`.

## 5. Background task management — DONE
Background Bash now CAPTURES output (was DEVNULL) and tracks status. New `BashOutput` tool reads incremental
output, reports running/exit code/elapsed, kills on demand, and lists all tasks. Test:
`test_background_task_captures_output_and_status`.

## 7. Plan mode with ExitPlanMode (Claude-Code-style) — DONE
Axion's plan mode used to require typing `/plan` then `/plan execute`. Now the model has an `ExitPlanMode`
tool: in plan mode it researches read-only, then calls ExitPlanMode with its plan, which the REPL renders
and asks the user to approve. On approval, plan mode turns off and the model implements; on rejection it
revises. (A plain "make a plan" still just produces a text plan, no mode needed.) Test:
`test_exit_plan_mode_approval_flow`. Suite 198.

## 8. MCP wired end-to-end + Playwright (browser automation) — DONE (suite 202)
MCP was scaffolding: config was parsed but servers were never connected and their tools never reached the
model. Now `_setup_mcp()` (cli/main.py) connects configured stdio servers at REPL startup, registers each
tool as `mcp__<server>__<tool>` (required_permission=workspace-write, so it prompts by default), routes
calls through `BuiltinToolExecutor._exec_mcp_tool` -> the server, and disconnects on exit. Sub-agents do NOT
start MCP servers (only the interactive path), so fan-out doesn't spawn browsers.
Windows fix: `.cmd`/`.bat` launchers (npx, npm) are run through COMSPEC since CreateProcess can't exec them
directly; command resolved with shutil.which. Init timeout raised to 180s (first-run npx downloads are slow).
Validated live against `@playwright/mcp` — 26 browser tools (navigate/click/type/fill_form/evaluate/...).
Enabled for Rex by adding the server to `~/.axion/settings.json`:
  {"mcpServers": {"playwright": {"type":"stdio","command":"npx","args":["-y","@playwright/mcp@latest","--headless"]}}}
Remove `--headless` to watch the browser. Tests: `test_executor_routes_mcp_tool_calls`, MCP transport tests.

## 9. Working skills — DONE (suite 209)
Skill tool registered (model can invoke), skills injected into the system prompt (# Skills), and
`/<name> args` runs a skill file as a turn. `execute_skill` substitutes {{args}}, $ARGUMENTS, $1..$9.
Search dirs deduped + home dirs added; `list_skills`/`render_skills_for_prompt` added. Create a skill at
`.axion/skills/<name>.md` (frontmatter name/description + body). Tests: test_skill_*.

## 15. Smooth per-token streaming + tool spinner — DONE (suite 217)
The REPL used to buffer model output until a blank line or a *closed* code fence, then dump the whole
block — so on a slow/self-hosted model the cursor sat frozen through a long paragraph or code block and
then a wall of text appeared ("looks like nothing is running"). Two fixes:
- **Line granularity:** `MarkdownStreamState.push_stream()` emits each COMPLETED line the moment its
  newline arrives — prose as Markdown, lines inside a ``` fence raw (indentation preserved) so code
  streams live. Tests: test_push_stream_*.
- **Per-token:** `LiveStreamer` (render.py) shows the in-progress *trailing* line in a one-line Rich
  `Live` region that updates as tokens arrive, so text visibly types out mid-line like Claude Code.
  Completed lines scroll into history (so it never fights terminal height / arbitrarily long replies).
  Degrades to line-granular if Live can't run (not a TTY) or `AXION_STREAM=lines`. Test:
  test_live_streamer_*.
- **Tool spinner:** a "Running <tool>…" spinner shows while a tool actually executes (starts on
  `on_tool_use`, which fires AFTER any permission prompt; stops on `on_tool_result`), so a slow Bash /
  WebFetch no longer looks frozen.
Wired in `cli/main.py` (`_emit_segment`, `repl_streamer`, `_stop_tool_spinner`) at the delta / tool /
end-of-turn / interrupt sites.
- **Animated spinner with no `[K` on cmd.exe:** the old Rich-Status spinner emitted VT escapes (`ESC[K`)
  that Windows consoles leaked as literal `[K` (worsened by a separate stderr console interleaving with
  stdout). The `Spinner` now animates by redrawing one line with a carriage return (`\r`) in a background
  thread — **no VT codes at all** — so it spins cleanly on every terminal, cmd.exe included, and clears its
  line with `\r`+spaces on stop. `spinner_mode()` = animate on any TTY (else off; `AXION_NO_SPINNER=1`
  forces off). The per-token Live typing region still needs real VT, so it's gated separately by
  `rich_live_ok()` (VT-safe terminals only — Windows Terminal / non-legacy / non-Windows) and falls back to
  line-granular streaming elsewhere; `AXION_STREAM=lines` forces that fallback. Net on cmd.exe: animated
  spinner + smooth line-by-line text, zero artifacts.

## 17. Cold-start tolerance (self-hosted endpoints) — DONE (suite 221)
A scaled-to-zero container (Modal) returns a redirect/gateway status (303/307/308/502/503/504) or refuses
the connection while it boots, so the FIRST request after idle failed with "API error 303: Turn failed at
iteration 1". `_stream_raw_bytes` now waits those out — polling every 3s up to 180s (bounded so a truly-down
endpoint still errors) — and retries transparently, with the animated spinner covering the wait. The normal
retry budget is untouched. Test: test_cold_start_redirect_is_waited_out.

## 16. Loop guard (anti-flailing) + clean Ctrl-C — DONE (suite 220)
A weaker model could burn all 50 tool iterations flailing (e.g. hunting nonexistent files with
`find/ls/wc` across many dirs), wasting tokens/time before the hard cap fired. `run_turn` now breaks early
on either signal: the SAME (tool, input) call issued 3×, OR a cumulative **10 tool results that carry no
new information** — empty/trivial/error, or an exact duplicate of a result already seen this turn
(`_batch_low_value` + `_seen_results`). The duplicate check is what catches the real case: varied commands
(`find …artifacts-XXXX`) whose results keep repeating. Appends "Rex stopped itself: …" so the user can
redirect. Plus a "Don't loop" rule in both Rex identities. Tests: test_loop_guard_stops_repeated_tool_calls,
test_loop_guard_stops_varied_dead_end_commands.
- **Ctrl-C now stops the turn instead of crashing Rex.** The interrupt was only checked during streaming,
  so a Ctrl-C mid tool-loop kept running tools, and any exception from the unwinding got wrapped into a
  fatal `ConversationError` ("Turn failed at iteration N") that killed the REPL. Now `is_interrupted` is
  checked at the top of each iteration and after each tool batch (clean break, `summary.interrupted`), and
  the `except` treats an interrupted turn as a clean stop (keeps the partial reply, drops any dangling
  tool_use so the session stays well-formed). One Ctrl-C → back to the prompt. Test:
  test_interrupt_during_tool_loop_stops_cleanly.

## 19. Parallel permission de-dup — DONE (suite 223)
Fanning out several Agent spawns in one turn made every spawn prompt separately, even after "allow
always" — because the parallel calls all hit the permission check before the first decision was cached
(a race). `_resolve_permission` now serializes prompts under a lock and re-checks the cache inside it
(`PermissionPolicy.cached_decision`), so once you allow-always a tool, the other concurrent/later calls
return the cached allow instead of re-asking. Test: test_parallel_permission_prompts_only_once.

## 18. Live multi-agent dashboard + eager delegation — DONE (suite 222)
Two asks: sub-agents didn't spawn on their own, and there was no good way to watch a fan-out.
- **Eager delegation:** the tool-use guidance (prompt.py) is now a directive with concrete triggers
  ("2+ independent chunks of real work → spawn an Agent for each, in one turn"), so Rex fans out without
  being told. (Speedup is sub-linear on a single A100 — agents share the GPU.)
- **Dashboard:** `axion/cli/agent_dashboard.py` `AgentDashboard` — one live panel showing every running
  sub-agent as a row (icon, label, what it's doing now, tokens), updating in place via a Rich `Live`
  table on a VT-capable terminal, degrading to one concise labelled line per event on legacy cmd.exe
  (gated by `rich_live_ok`; markup disabled so `[label]` survives). Shared across the concurrent
  `_exec_agent` tasks; starts on the first agent, tears down when the last finishes. Chosen over spawning
  a separate OS window per agent (fragile, doesn't scale, closes on completion losing the output).
- **Per-agent logs:** each sub-agent's full transcript (task + progress + result) is written to
  `.axion/agent-logs/<label>.log` so you can open/tail any agent's detail, and it persists after it
  finishes. The "Running Agent…" spinner is suppressed (the dashboard shows the progress instead).
  Test: test_agent_dashboard_tracks_each_agent.

## 10. Streaming robustness — DONE
A truncated stream that leaves unparseable tool-call JSON is now detected (`has_incomplete_tool_call`) and
the request is retried up to twice instead of executing a garbled call. Test: test_incomplete_tool_call_*.

## 11. Conversation rewind — DONE
`/rewind [N]` drops the last N user turns (a user message + everything after) so you can retry from a good
point; tool-result messages aren't counted as turn starts. (`/undo` remains the git undo.) Test: test_rewind_*.

## 12. @-file mention cap — DONE (feature already existed)
`@path` injection already worked; added a total-size cap (AXION_MAX_TOOL_RESULT_CHARS) so several big @files
can't overflow a small window.

## 13. Command/path-scoped permissions — DONE
Rules can now match the tool INPUT, not just its name: `Bash(git *)`, `Bash(rm *)`, `Edit(src/*)`,
`WebFetch(https://api.example.com/*)`. `_extract_specifier` + glob matching in `_matches_rule`. Put them in
allowedTools/deniedTools in settings.json. Tests: test_command_scoped_permission_rules.

## 14. Richer /cost — DONE
Per-category cost (input/output/cache), cache-hit %, turn count, correct per-model pricing, and a per-model
breakdown when more than one model was used (UsageTracker.by_model). Test: test_per_model_usage_tracking.

## 6. IDE integration — NOT DONE (separate track)
Living in VS Code (selection awareness, open-file, inline diffs) is a real extension project, not a harness
change. There is an `axion-vscode` folder to build on. Highest daily value, highest effort — do it as its
own workstream, not part of the harness pass.
