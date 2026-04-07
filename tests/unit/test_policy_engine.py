"""Tests for policy engine with condition combinators."""

from axion.runtime.policy_engine import (
    ConditionAnd,
    ConditionGreenAt,
    ConditionLaneCompleted,
    ConditionOr,
    ConditionReviewPassed,
    ConditionStaleBranch,
    LaneBlocker,
    LaneContext,
    PolicyAction,
    PolicyActionSpec,
    PolicyEngine,
    PolicyRule,
    ReviewStatus,
)


def test_condition_and():
    ctx = LaneContext(lane_id="lane-1", completed=True, review_status=ReviewStatus.APPROVED)
    cond = ConditionAnd([ConditionLaneCompleted(), ConditionReviewPassed()])
    assert cond.evaluate(ctx)

    ctx2 = LaneContext(lane_id="lane-2", completed=True, review_status=ReviewStatus.PENDING)
    assert not cond.evaluate(ctx2)


def test_condition_or():
    ctx = LaneContext(lane_id="lane-1", stale_branch=True)
    cond = ConditionOr([ConditionStaleBranch(), ConditionLaneCompleted()])
    assert cond.evaluate(ctx)


def test_condition_green_at():
    ctx = LaneContext(lane_id="lane-1", green_level=5)
    assert ConditionGreenAt(3).evaluate(ctx)
    assert ConditionGreenAt(5).evaluate(ctx)
    assert not ConditionGreenAt(6).evaluate(ctx)


def test_policy_engine_evaluate():
    engine = PolicyEngine(rules=[
        PolicyRule(
            name="merge",
            condition=ConditionAnd([ConditionLaneCompleted(), ConditionReviewPassed()]),
            action=PolicyActionSpec(action=PolicyAction.MERGE_TO_DEV),
            priority=100,
        ),
        PolicyRule(
            name="recover_stale",
            condition=ConditionStaleBranch(),
            action=PolicyActionSpec(action=PolicyAction.RECOVER_ONCE),
            priority=50,
        ),
    ])

    ctx = LaneContext(
        lane_id="lane-1", completed=True,
        review_status=ReviewStatus.APPROVED, stale_branch=True,
    )
    actions = engine.evaluate(ctx)
    assert len(actions) == 2
    assert actions[0].action == PolicyAction.MERGE_TO_DEV  # Higher priority first
    assert actions[1].action == PolicyAction.RECOVER_ONCE


def test_policy_engine_first():
    engine = PolicyEngine.default_rules()
    ctx = LaneContext(
        lane_id="lane-1", completed=True,
        review_status=ReviewStatus.APPROVED,
    )
    action = engine.evaluate_first(ctx)
    assert action is not None
    assert action.action == PolicyAction.MERGE_TO_DEV


def test_no_matching_rules():
    engine = PolicyEngine(rules=[])
    ctx = LaneContext(lane_id="lane-1")
    assert engine.evaluate(ctx) == []
    assert engine.evaluate_first(ctx) is None
