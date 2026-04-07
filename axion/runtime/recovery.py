"""Failure recovery recipes with actual retry execution.

Maps to: rust/crates/runtime/src/recovery_recipes.rs
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)


class FailureScenario(enum.Enum):
    TRUST_PROMPT_UNRESOLVED = "trust_prompt_unresolved"
    PROMPT_MISDELIVERY = "prompt_misdelivery"
    STALE_BRANCH = "stale_branch"
    COMPILE_RED_CROSS_CRATE = "compile_red_cross_crate"
    MCP_HANDSHAKE_FAILURE = "mcp_handshake_failure"
    PARTIAL_PLUGIN_STARTUP = "partial_plugin_startup"
    PROVIDER_FAILURE = "provider_failure"


class RecoveryStep(enum.Enum):
    ACCEPT_TRUST_PROMPT = "accept_trust_prompt"
    REDIRECT_PROMPT_TO_AGENT = "redirect_prompt_to_agent"
    REBASE_BRANCH = "rebase_branch"
    CLEAN_BUILD = "clean_build"
    RETRY_MCP_HANDSHAKE = "retry_mcp_handshake"
    RESTART_PLUGIN = "restart_plugin"
    RESTART_WORKER = "restart_worker"
    ESCALATE_TO_HUMAN = "escalate_to_human"
    WAIT_AND_RETRY = "wait_and_retry"
    LOG_AND_CONTINUE = "log_and_continue"


class EscalationPolicy(enum.Enum):
    ALERT_HUMAN = "alert_human"
    LOG_AND_CONTINUE = "log_and_continue"
    ABORT = "abort"


@dataclass
class RecoveryRecipe:
    """A recovery recipe for a specific failure scenario."""

    scenario: FailureScenario
    steps: list[RecoveryStep]
    max_attempts: int = 3
    escalation: EscalationPolicy = EscalationPolicy.ALERT_HUMAN
    backoff_ms: int = 1000
    description: str = ""


@dataclass
class RecoveryContext:
    """Context available to recovery execution."""

    scenario: FailureScenario
    worker_id: str | None = None
    plugin_name: str | None = None
    mcp_server: str | None = None
    branch: str | None = None
    error_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecoveryEvent:
    """Event recorded during recovery execution."""

    step: RecoveryStep
    attempt: int
    success: bool
    message: str = ""
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class RecoveryResult:
    """Result of a recovery attempt."""

    success: bool
    attempts: int = 0
    message: str = ""
    events: list[RecoveryEvent] = field(default_factory=list)
    escalated: bool = False


# ---------------------------------------------------------------------------
# Step executors
# ---------------------------------------------------------------------------

# Registry of step execution functions
StepExecutor = Callable[[RecoveryContext], Awaitable[bool]]
_step_executors: dict[RecoveryStep, StepExecutor] = {}


def register_step_executor(step: RecoveryStep, executor: StepExecutor) -> None:
    """Register an executor for a recovery step."""
    _step_executors[step] = executor


async def _default_step_executor(step: RecoveryStep, context: RecoveryContext) -> bool:
    """Default executor that logs and returns success for simple steps."""
    match step:
        case RecoveryStep.LOG_AND_CONTINUE:
            logger.info("Recovery: logging and continuing for %s", context.scenario.value)
            return True
        case RecoveryStep.WAIT_AND_RETRY:
            logger.info("Recovery: waiting before retry for %s", context.scenario.value)
            await asyncio.sleep(1.0)
            return True
        case RecoveryStep.ESCALATE_TO_HUMAN:
            logger.warning(
                "Recovery: escalating to human for %s: %s",
                context.scenario.value, context.error_message,
            )
            return True  # Escalation "succeeds" — it's been handed off
        case _:
            # Check registered executors
            executor = _step_executors.get(step)
            if executor:
                return await executor(context)
            logger.warning("No executor for recovery step %s, skipping", step.value)
            return False


# ---------------------------------------------------------------------------
# Recipe registry
# ---------------------------------------------------------------------------

def recipe_for(scenario: FailureScenario) -> RecoveryRecipe:
    """Get the recovery recipe for a given failure scenario."""
    recipes: dict[FailureScenario, RecoveryRecipe] = {
        FailureScenario.TRUST_PROMPT_UNRESOLVED: RecoveryRecipe(
            scenario=scenario,
            steps=[RecoveryStep.ACCEPT_TRUST_PROMPT],
            max_attempts=1,
            description="Auto-resolve trust prompt if allowlisted",
        ),
        FailureScenario.PROMPT_MISDELIVERY: RecoveryRecipe(
            scenario=scenario,
            steps=[RecoveryStep.REDIRECT_PROMPT_TO_AGENT, RecoveryStep.WAIT_AND_RETRY],
            max_attempts=3,
            backoff_ms=500,
            description="Redirect prompt to correct target with retry",
        ),
        FailureScenario.STALE_BRANCH: RecoveryRecipe(
            scenario=scenario,
            steps=[RecoveryStep.REBASE_BRANCH],
            max_attempts=2,
            description="Rebase stale branch from upstream",
        ),
        FailureScenario.COMPILE_RED_CROSS_CRATE: RecoveryRecipe(
            scenario=scenario,
            steps=[RecoveryStep.CLEAN_BUILD],
            max_attempts=2,
            description="Clean build artifacts and rebuild",
        ),
        FailureScenario.MCP_HANDSHAKE_FAILURE: RecoveryRecipe(
            scenario=scenario,
            steps=[RecoveryStep.RETRY_MCP_HANDSHAKE, RecoveryStep.WAIT_AND_RETRY],
            max_attempts=3,
            backoff_ms=2000,
            description="Retry MCP handshake with backoff",
        ),
        FailureScenario.PARTIAL_PLUGIN_STARTUP: RecoveryRecipe(
            scenario=scenario,
            steps=[RecoveryStep.RESTART_PLUGIN],
            max_attempts=2,
            description="Restart failed plugin",
        ),
        FailureScenario.PROVIDER_FAILURE: RecoveryRecipe(
            scenario=scenario,
            steps=[RecoveryStep.RESTART_WORKER, RecoveryStep.WAIT_AND_RETRY],
            max_attempts=3,
            backoff_ms=5000,
            escalation=EscalationPolicy.LOG_AND_CONTINUE,
            description="Restart worker with backoff, log if persistent",
        ),
    }
    return recipes.get(scenario, RecoveryRecipe(
        scenario=scenario,
        steps=[RecoveryStep.ESCALATE_TO_HUMAN],
        max_attempts=1,
        escalation=EscalationPolicy.ABORT,
        description="Unknown scenario — escalate immediately",
    ))


# ---------------------------------------------------------------------------
# Recovery executor
# ---------------------------------------------------------------------------

async def attempt_recovery(
    scenario: FailureScenario,
    context: RecoveryContext | None = None,
) -> RecoveryResult:
    """Execute the recovery recipe for a scenario.

    Runs steps in order, retrying up to max_attempts with backoff.
    Falls back to escalation policy if all attempts fail.
    """
    recipe = recipe_for(scenario)
    ctx = context or RecoveryContext(scenario=scenario)
    result = RecoveryResult()

    for attempt in range(1, recipe.max_attempts + 1):
        result.attempts = attempt
        all_steps_ok = True

        for step in recipe.steps:
            try:
                success = await _default_step_executor(step, ctx)
            except Exception as exc:
                logger.error("Recovery step %s failed: %s", step.value, exc)
                success = False

            event = RecoveryEvent(
                step=step, attempt=attempt, success=success,
                message=f"Step {step.value}: {'OK' if success else 'FAILED'}",
            )
            result.events.append(event)

            if not success:
                all_steps_ok = False
                break

        if all_steps_ok:
            result.success = True
            result.message = f"Recovered after {attempt} attempt(s)"
            return result

        # Backoff before retry
        if attempt < recipe.max_attempts:
            delay_ms = recipe.backoff_ms * (2 ** (attempt - 1))
            logger.info("Recovery attempt %d failed, retrying in %dms", attempt, delay_ms)
            await asyncio.sleep(delay_ms / 1000.0)

    # All attempts exhausted — escalate
    result.message = f"Recovery failed after {recipe.max_attempts} attempt(s)"

    match recipe.escalation:
        case EscalationPolicy.ALERT_HUMAN:
            result.escalated = True
            result.message += " — escalated to human"
            logger.warning("Recovery escalated: %s", result.message)
        case EscalationPolicy.LOG_AND_CONTINUE:
            result.message += " — logged and continuing"
            logger.warning("Recovery failed but continuing: %s", result.message)
        case EscalationPolicy.ABORT:
            result.escalated = True
            result.message += " — aborting"
            logger.error("Recovery failed, aborting: %s", result.message)

    return result
