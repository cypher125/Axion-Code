"""Plan mode — read-only exploration and design before implementation.

When plan mode is active:
- Only read-only tools are allowed (Read, Glob, Grep, WebSearch, WebFetch)
- Write/Edit/Bash are blocked
- The system prompt is augmented with planning instructions
- The AI explores the codebase, designs an approach, and presents a plan
- User approves or rejects the plan before any code changes
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Tools allowed in plan mode (read-only only)
PLAN_MODE_ALLOWED_TOOLS = {
    "Read", "Glob", "Grep", "WebSearch", "WebFetch",
    "ToolSearch", "Agent",  # Agent can explore
    "ExitPlanMode",  # how the model presents its plan for approval
}

# Tools blocked in plan mode
PLAN_MODE_BLOCKED_TOOLS = {
    "Bash", "Write", "Edit", "NotebookEdit", "Skill",
}

PLAN_MODE_SYSTEM_PROMPT = """
# Plan Mode Active

You are in PLAN MODE. This means:

1. **DO NOT write or modify any files.** Only read, search, and explore.
2. **DO NOT run commands** that change state (no git commit, no file creation, no installs).
3. **DO explore thoroughly.** Read relevant files, search for patterns, understand the architecture.
4. **DO design a concrete plan.** After exploring, present a clear implementation plan.

## Your plan should include:

### Summary
One paragraph describing what needs to be done and why.

### Files to Modify
List each file that needs changes, with a brief description of what changes.

### Files to Create
List any new files needed, with their purpose.

### Implementation Steps
Numbered steps in order of execution.

### Risks & Considerations
Anything that could go wrong or needs careful handling.

### Verification
How to test that the implementation works.

## When you're done exploring and have a plan:
Call the **ExitPlanMode** tool with your full plan (as `plan`). It presents the plan to the user for
approval. If they approve, plan mode turns off and you should implement the plan immediately. If they
reject, revise based on their feedback. Do not write files or run state-changing commands until approved.
"""


@dataclass
class PlanState:
    """Tracks the current plan mode state."""

    active: bool = False
    task_description: str = ""
    plan_text: str = ""
    files_explored: list[str] = field(default_factory=list)
    files_to_modify: list[str] = field(default_factory=list)
    files_to_create: list[str] = field(default_factory=list)
    approved: bool = False

    def reset(self) -> None:
        self.active = False
        self.task_description = ""
        self.plan_text = ""
        self.files_explored.clear()
        self.files_to_modify.clear()
        self.files_to_create.clear()
        self.approved = False


def is_tool_allowed_in_plan_mode(tool_name: str) -> bool:
    """Check if a tool is allowed during plan mode."""
    return tool_name in PLAN_MODE_ALLOWED_TOOLS


def get_plan_mode_denial_message(tool_name: str) -> str:
    """Get the message shown when a tool is blocked in plan mode."""
    return (
        f"Tool '{tool_name}' is blocked in plan mode. "
        f"Only read-only tools are allowed (Read, Glob, Grep, WebSearch, WebFetch). "
        f"Exit plan mode with /plan execute or /plan exit to use write tools."
    )
