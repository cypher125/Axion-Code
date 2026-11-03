# Axion Audit — 2026-09-16

Findings from a four-way parallel review of Axion (API/streaming, conversation/compaction,
tools/permissions, config/memory/CLI/MCP). Deduplicated and ranked. Items confirmed by more than
one reviewer are marked (xN). Already fixed this session: `/compact` threshold, `--system-prompt`
flag, token estimator counting tool results, per-iteration preflight, tool-output cap, context-window
default — see HANDOFF.md in the REX repo.

## Batch 1 — Rex-breaking correctness — DONE 2026-09-16 (all six fixed, tests added, suite 180 passing)

1. CRITICAL — Auto-compaction never fires on the custom provider (Rex's provider). Streamed
   `input_tokens` are only in the trailing chunk, but the consumer reads them from message_start, so
   `cumulative_input_tokens` stays 0 and `_maybe_auto_compact` never triggers. This is the root cause
   of the repeated 16k context-overflow crashes; only the new preflight saved it.
   Fix: api/openai_compat.py stream usage → surface input_tokens; conversation.py MessageDelta handler
   also read input_tokens. (api reviewer #2)
2. CRITICAL — Compaction orphans tool_result blocks → next request rejected (provider 400), killing the
   turn. Split ignores tool_use/tool_result pairing. Sharpened by the new per-iteration preflight.
   Fix: snap the cut so recent never starts with an orphaned tool_result; apply in both compact paths.
   (conversation reviewer #1, config reviewer #10) (x2)
3. HIGH — "Streaming" buffers the whole response before yielding anything; Rex shows nothing until the
   full answer is done. httpx `.post()` reads the body fully. Also openai_compat timeout is 120s vs 300s.
   Fix: use `http.stream("POST", ...)`; raise timeout to 300s. (api reviewer #3)
4. HIGH — Session file rotation crashes on Windows and never prunes; `save()` throws and silently loses
   the snapshot → data loss. `Path.rename` over an existing file raises on Windows; prune branch is dead.
   Fix: use `os.replace`; fix the prune. (conversation reviewer #4, config reviewer #4) (x2)
5. MEDIUM — `/context` and the overflow banner hardcode 200,000 tokens instead of the real window.
   Fix: call `_context_window_for(model)`. (config reviewer #8)
6. MEDIUM — Tool-output cap not applied on the error path or to MCP/plugin tools.
   Fix: apply `_cap_tool_result` centrally in conversation.py after execute. (tools reviewer #6)

## Batch 2 — Security — DONE (#7,#8,#9,#11) 2026-09-16; #10 deferred. Suite 190 passing.
Done: #7 — sub-agents now inherit the parent's permission mode (was hardcoded full access); `prompt`
subcommand no longer hardcodes "allow". #8 — write tools (Write/Edit/MultiEdit/NotebookEdit) are confined
to the working directory in workspace-write mode (danger-full-access unrestricted; read-only already blocks
them). #9 — "allow once" no longer caches as "allow always" (prompter returns the real choice; only
allow-always is remembered). #11 — WebFetch blocks internal/loopback/link-local/metadata addresses
(re-checked on every redirect) and wraps page bodies as untrusted content.
Deferred: #10 — command/path-scoped permission rules (e.g. allow `git *`, deny `rm *`). Bigger design change
(parse tool input, input-aware cache key); worth doing before Rex is multi-user, but not blocking for
single-user use. The dead bwrap sandbox (Batch 3 E) stays deferred — Linux-only; #8 is the Windows protection.

### Original Batch 2 list (for reference)

7. CRITICAL [SEC] — Agent tool escalates to full access: sub-agents spawn with permission mode
   hardcoded to "allow", bypassing the parent's mode entirely, and inherit the full env (secrets).
   Fix: propagate the parent's real mode/rules; sub-agent ≤ parent privilege. (tools reviewer #1)
8. CRITICAL [SEC] — "workspace-write" does not confine writes; the boundary-check and the entire Bash
   sandbox (bwrap/network isolation) exist but are never called. Effectively whole-machine write.
   Fix: call a real boundary check (Path.is_relative_to) in every file handler; wire the sandbox to
   the mode, or document Bash as full-access. (tools reviewer #2)
9. HIGH [SEC] — "Allow once" behaves as "allow always"; one approval whitelists a tool for the session.
   Fix: return the chosen kind; cache only on "always". (tools reviewer #3)
10. HIGH [SEC] — Permission rules match tool name only; no command/path-level allow/deny.
    Fix: parse input_json; support Bash-command / file-path scoped rules; input-aware cache key. (tools #4)
11. MEDIUM [SEC] — WebFetch: no SSRF protection (fetches internal/link-local IPs, follows redirects),
    and fetched page content is returned as trusted, un-delimited text (prompt-injection vector).
    Fix: block private/loopback IPs (re-check after redirects); wrap fetched bodies as untrusted. (tools #5)

## Batch 3 — Features — DONE (A, C, D) 2026-09-16; B deferred, E folded into Batch 2. Suite 186 passing.
Done: A — MemoryStore wired into the system prompt + a `Remember` tool + `/memory` repointed at the store
(memory bugs fixed: index refresh, name-collision hashing, multiline-frontmatter). C — heuristic compaction
now keeps tool names + truncated tool outputs in the summary (was text-only). D — `MultiEdit` tool (atomic
multi-hunk edits). Deferred: B (real tokenizer) — needs the model tokenizer locally or the server /tokenize
endpoint; revisit with the A100. E (engage bwrap sandbox) — Linux-only; on Windows the path-confinement in
Batch 2 #8 is the real protection.

### Original Batch 3 list (for reference)

A. Wire the MemoryStore into context — the "Rex remembers you" feature. The whole memory subsystem is
   dead code; `/memory` edits CLAUDE.md instead. Load memories at startup into the system prompt and
   repoint `/memory add|list|show` at the store. (config reviewer A, conversation reviewer note) (x2)
B. Real tokenizer instead of the 4-chars/token heuristic; images undercounted. Makes preflight reliable
   on a small window. (conversation + api notes)
C. Wire model-based compaction (`model_compact_session` exists, never called) into the auto path; biggest
   context-retention quality win. (conversation reviewer #5)
D. Multi-edit / apply-patch tool (scaffolding already in file_ops.py); fewer round-trips, fewer races.
E. Actually engage the dormant Bash sandbox for workspace-write (ties to #8).

## Batch 4 — Providers / MCP / polish — MOSTLY DONE 2026-09-16. Suite 193 passing.
Done: #12 MCP stdio now uses newline-delimited JSON (was Content-Length → all servers returned zero tools);
stderr drained; disconnect awaits tasks + closes writer; 10 MB line limit. #13 `/model` rebuilds the provider.
#14 cost budget priced with the active model (was always Sonnet → overspent). #16 SSE parser flush (last
frame no longer lost); finish_reason length→max_tokens + content_filter; xAI streaming usage. #17 `/clear`
resets usage+compaction; config deep-merge deep-copies (no source aliasing) and UNIONS permission
allow/deny lists (was overwrite). Quick wins: Edit gives a clear error on non-UTF-8 (was silent/corrupting);
Read off-by-one + offset=0 fixed; Bash timeout floored at 1s.
Deferred (low value for Rex): #15 Codex tool_use (Codex is not Rex's provider); #18 thinking blocks (Rex runs
thinking off); `/session switch` usage rebuild + TodoWrite process-global state (minor); Batch 2 #10
command/path-scoped permission rules (do before multi-user).

### Original Batch 4 list (for reference)

12. HIGH — MCP stdio uses wrong framing (Content-Length vs newline-delimited JSON-RPC); every MCP server
    silently returns zero tools. Also stderr never drained (deadlock/leak). Fix: newline framing; drain
    stderr; await cancelled read task; close writer. (config reviewer #1, #2)
13. HIGH — `/model` switches the model name but never rebuilds the provider client → wrong provider/key.
    Fix: call `_rebuild_provider_for_runtime`. (config reviewer #3)
14. HIGH — Cost budget always priced as Sonnet → overspends on other models. Fix: price with the model's
    rates in the budget checks; set usage_tracker.model. (conversation reviewer #2)
15. CRITICAL (Codex only) — Codex tool calls never execute (stop_reason mapped to end_turn). Not Rex's
    provider, so lower priority for Rex. Fix: set tool_use when function_call present. (api reviewer #1)
16. MEDIUM — finish_reason "length"/"content_filter" not mapped to max_tokens; xAI streaming requests no
    usage; SSE parser has no flush (last frame lost if no trailing blank line). (api reviewers #4,#5,#6)
17. MEDIUM — `/clear` and `/session switch` don't reset usage/compaction state; config deep-merge mutates
    source dicts and overwrites permission lists instead of unioning. (config reviewers #5,#6,#7)
18. MEDIUM — Thinking blocks dropped from stored assistant message (lost on resume; may break strict
    providers). (conversation reviewer #3)
19. LOW — Edit reads strict UTF-8 (Read uses errors=replace) → a readable file may be un-editable; Read
    offset+limit off-by-one and offset=0 treated as unset; Bash timeout no lower bound; TodoWrite uses
    process-global state (parallel agents clobber). (tools reviewers #7,#8,#11,#12)
20. LOW — max_iterations ends silently leaving a dangling tool_use; context-window 400s not converted to
    ContextWindowExceededError; retry backoff has no jitter. (conversation #7, api #10, #9)
