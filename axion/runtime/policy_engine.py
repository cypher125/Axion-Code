"""Git lane policy engine with condition combinators and chained actions.

Maps to: rust/crates/runtime/src/policy_engine.rs
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

GreenLevel = int  # 0-255


# ---------------------------------------------------------------------------
# Lane context
# ---------------------------------------------------------------------------

class ReviewStatus(enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DiffScope(enum.Enum):
    FULL = "full"
    SCOPED = "scoped"


class LaneBlocker(enum.Enum):
    NONE = "none"
    STARTUP = "startup"
    EXTERNAL = "external"


@dataclass
class LaneContext:
    """Context for policy evaluation."""

    lane_id: str
    green_level: GreenLevel = 0
    branch_freshness_ms: int = 0
    blocker: LaneBlocker = LaneBlocker.NONE
    review_status: ReviewStatus = ReviewStatus.PENDING
    diff_scope: DiffScope = DiffScope.FULL
    completed: bool = False
    reconciled: bool = False
    timed_out: bool = False
    stale_branch: bool = False


# ---------------------------------------------------------------------------
# Conditions (combinators matching Rust enum)
# ---------------------------------------------------------------------------

class PolicyCondition:
    """Base class for policy conditions."""

    def evaluate(self, ctx: LaneContext) -> bool:
        raise NotImplementedError


class ConditionAnd(PolicyCondition):
    def __init__(self, conditions: list[PolicyCondition]) -> None:
        self.conditions = conditions

    def evaluate(self, ctx: LaneContext) -> bool:
        return all(c.evaluate(ctx) for c in self.conditions)


class ConditionOr(PolicyCondition):
    def __init__(self, conditions: list[PolicyCondition]) -> None:
        self.conditions = conditions

    def evaluate(self, ctx: LaneContext) -> bool:
        return any(c.evaluate(ctx) for c in self.conditions)


class ConditionGreenAt(PolicyCondition):
    def __init__(self, level: GreenLevel) -> None:
        self.level = level

    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.green_level >= self.level


class ConditionStaleBranch(PolicyCondition):
    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.stale_branch


class ConditionStartupBlocked(PolicyCondition):
    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.blocker == LaneBlocker.STARTUP


class ConditionLaneCompleted(PolicyCondition):
    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.completed


class ConditionLaneReconciled(PolicyCondition):
    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.reconciled


class ConditionReviewPassed(PolicyCondition):
    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.review_status == ReviewStatus.APPROVED


class ConditionScopedDiff(PolicyCondition):
    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.diff_scope == DiffScope.SCOPED


class ConditionTimedOut(PolicyCondition):
    def __init__(self, duration_ms: int = 0) -> None:
        self.duration_ms = duration_ms

    def evaluate(self, ctx: LaneContext) -> bool:
        return ctx.timed_out


class ConditionAlways(PolicyCondition):
    def evaluate(self, ctx: LaneContext) -> bool:
        return True


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

class PolicyAction(enum.Enum):
    MERGE_TO_DEV = "merge_to_dev"
    MERGE_FORWARD = "merge_forward"
    RECOVER_ONCE = "recover_once"
    ESCALATE = "escalate"
    CLOSEOUT_LANE = "closeout_lane"
    CLEANUP_SESSION = "cleanup_session"
    RECONCILE = "reconcile"
    NOTIFY = "notify"
    BLOCK = "block"


@dataclass
class PolicyActionSpec:
    """An action with optional parameters."""

    action: PolicyAction
    reason: str = ""
    channel: str = ""  # For NOTIFY


@dataclass
class ChainedAction:
    """Multiple actions executed in sequence."""

    actions: list[PolicyActionSpec] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

@dataclass
class PolicyRule:
    """A condition → action mapping with priority."""

    name: str
    condition: PolicyCondition
    action: PolicyActionSpec | ChainedAction
    priority: int = 0
    description: str = ""


# ---------------------------------------------------------------------------
# Policy engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """Evaluates policy rules against lane context.

    Maps to: rust/crates/runtime/src/policy_engine.rs::PolicyEngine
    Supports condition combinators (And/Or), chained actions, and priority ordering.
    """

    def __init__(self, rules: list[PolicyRule] | None = None) -> None:
        self._rules = sorted(rules or [], key=lambda r: r.priority, reverse=True)

    def add_rule(self, rule: PolicyRule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: r.priority, reverse=True)

    def evaluate(self, context: LaneContext) -> list[PolicyActionSpec]:
        """Evaluate all rules and return applicable actions."""
        actions: list[PolicyActionSpec] = []

        for rule in self._rules:
            if rule.condition.evaluate(context):
                if isinstance(rule.action, ChainedAction):
                    actions.extend(rule.action.actions)
                else:
                    actions.append(rule.action)

        return actions

    def evaluate_first(self, context: LaneContext) -> PolicyActionSpec | None:
        """Return the first matching action (highest priority)."""
        for rule in self._rules:
            if rule.condition.evaluate(context):
                if isinstance(rule.action, ChainedAction):
                    return rule.action.actions[0] if rule.action.actions else None
                return rule.action
        return None

    @classmethod
    def default_rules(cls) -> PolicyEngine:
        """Create engine with default git lane policies."""
        return cls(rules=[
            PolicyRule(
                name="merge_approved",
                condition=ConditionAnd([ConditionLaneCompleted(), ConditionReviewPassed()]),
                action=PolicyActionSpec(action=PolicyAction.MERGE_TO_DEV),
                priority=100,
                description="Merge completed & approved lanes to dev",
            ),
            PolicyRule(
                name="block_startup",
                condition=ConditionStartupBlocked(),
                action=PolicyActionSpec(action=PolicyAction.BLOCK, reason="Startup blocker active"),
                priority=90,
            ),
            PolicyRule(
                name="escalate_external",
                condition=ConditionAnd([
                    ConditionOr([ConditionStaleBranch(), ConditionTimedOut()]),
                ]),
                action=PolicyActionSpec(
                    action=PolicyAction.ESCALATE,
                    reason="Branch stale or timed out",
                ),
                priority=80,
            ),
            PolicyRule(
                name="closeout_reconciled",
                condition=ConditionAnd([ConditionLaneCompleted(), ConditionLaneReconciled()]),
                action=ChainedAction(actions=[
                    PolicyActionSpec(action=PolicyAction.CLOSEOUT_LANE),
                    PolicyActionSpec(action=PolicyAction.CLEANUP_SESSION),
                ]),
                priority=70,
            ),
            PolicyRule(
                name="recover_stale",
                condition=ConditionStaleBranch(),
                action=PolicyActionSpec(action=PolicyAction.RECOVER_ONCE, reason="Branch is stale"),
                priority=50,
            ),
        ])
