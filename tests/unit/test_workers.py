"""Tests for worker state machine."""

from axion.runtime.workers import (
    Worker,
    WorkerFailureKind,
    WorkerPromptTarget,
    WorkerRegistry,
    WorkerStatus,
    WorkerTrustResolution,
)


def test_worker_lifecycle():
    w = Worker(cwd="/tmp")
    assert w.status == WorkerStatus.SPAWNING

    # Transition to trust required
    w.transition(WorkerStatus.TRUST_REQUIRED)
    assert w.status == WorkerStatus.TRUST_REQUIRED

    # Resolve trust
    w.resolve_trust(WorkerTrustResolution.AUTO_ALLOWLISTED)
    assert w.status == WorkerStatus.READY_FOR_PROMPT
    assert w.trust_gate_cleared

    # Deliver prompt
    success = w.deliver_prompt(WorkerPromptTarget.SHELL)
    assert success
    assert w.status == WorkerStatus.RUNNING

    # Finish
    w.finish()
    assert w.status == WorkerStatus.FINISHED
    assert w.is_terminal


def test_worker_prompt_misdelivery_retry():
    w = Worker(cwd="/tmp", status=WorkerStatus.READY_FOR_PROMPT)

    success = w.deliver_prompt(WorkerPromptTarget.WRONG_TARGET)
    assert not success
    assert w.status == WorkerStatus.READY_FOR_PROMPT  # Retrying

    success = w.deliver_prompt(WorkerPromptTarget.WRONG_TARGET)
    assert not success

    success = w.deliver_prompt(WorkerPromptTarget.WRONG_TARGET)
    assert not success
    assert w.status == WorkerStatus.FAILED  # Max attempts exceeded


def test_worker_fail():
    w = Worker(cwd="/tmp", status=WorkerStatus.RUNNING)
    w.fail(WorkerFailureKind.PROVIDER, "API error")
    assert w.status == WorkerStatus.FAILED
    assert w.is_terminal


def test_worker_restart():
    w = Worker(cwd="/tmp", status=WorkerStatus.FAILED)
    w.restart()
    assert w.status == WorkerStatus.SPAWNING
    assert not w.trust_gate_cleared
    assert w.prompt_delivery_attempts == 0


def test_worker_registry():
    reg = WorkerRegistry()
    w = reg.spawn(cwd="/tmp")
    assert len(reg.all_workers()) == 1

    w.transition(WorkerStatus.RUNNING)
    assert len(reg.active_workers()) == 1

    w.finish()
    assert len(reg.active_workers()) == 0
    assert len(reg.finished_workers()) == 1


def test_worker_registry_summary():
    reg = WorkerRegistry()
    reg.spawn(cwd="/tmp")
    reg.spawn(cwd="/tmp")
    w3 = reg.spawn(cwd="/tmp")
    w3.transition(WorkerStatus.RUNNING)

    summary = reg.summary()
    assert summary.get("spawning", 0) == 2
    assert summary.get("running", 0) == 1
