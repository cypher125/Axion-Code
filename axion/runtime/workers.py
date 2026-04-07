"""Worker state machine and registry with full lifecycle management.

Maps to: rust/crates/runtime/src/worker_boot.rs
"""

from __future__ import annotations

import enum
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


class WorkerStatus(enum.Enum):
    SPAWNING = "spawning"
    TRUST_REQUIRED = "trust_required"
    READY_FOR_PROMPT = "ready_for_prompt"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class WorkerFailureKind(enum.Enum):
    TRUST_GATE = "trust_gate"
    PROMPT_DELIVERY = "prompt_delivery"
    PROTOCOL = "protocol"
    PROVIDER = "provider"


class WorkerTrustResolution(enum.Enum):
    AUTO_ALLOWLISTED = "auto_allowlisted"
    MANUAL_APPROVAL = "manual_approval"


class WorkerPromptTarget(enum.Enum):
    SHELL = "shell"
    WRONG_TARGET = "wrong_target"
    UNKNOWN = "unknown"


@dataclass
class WorkerEvent:
    """Timestamped event in a worker's lifecycle."""

    seq: int
    kind: str
    status: WorkerStatus
    detail: str = ""
    payload: dict[str, Any] | None = None
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class Worker:
    """Represents a single agent worker instance.

    Implements the full state machine:
    SPAWNING → TRUST_REQUIRED → READY_FOR_PROMPT → RUNNING → FINISHED/FAILED
    """

    worker_id: str = field(default_factory=lambda: f"w-{uuid.uuid4().hex[:8]}")
    cwd: str = ""
    status: WorkerStatus = WorkerStatus.SPAWNING
    trust_auto_resolve: bool = False
    trust_gate_cleared: bool = False
    auto_recover_prompt_misdelivery: bool = True
    prompt_delivery_attempts: int = 0
    max_prompt_delivery_attempts: int = 3
    events: list[WorkerEvent] = field(default_factory=list)

    def transition(self, new_status: WorkerStatus, detail: str = "", **payload: Any) -> None:
        """Transition to a new status with event logging."""
        event = WorkerEvent(
            seq=len(self.events) + 1,
            kind=f"transition_{new_status.value}",
            status=new_status,
            detail=detail,
            payload=payload if payload else None,
        )
        self.events.append(event)
        self.status = new_status
        logger.debug("Worker %s → %s: %s", self.worker_id, new_status.value, detail)

    def resolve_trust(self, resolution: WorkerTrustResolution) -> None:
        """Resolve the trust gate and advance to ready state."""
        if self.status != WorkerStatus.TRUST_REQUIRED:
            logger.warning("Cannot resolve trust in status %s", self.status.value)
            return
        self.trust_gate_cleared = True
        self.transition(
            WorkerStatus.READY_FOR_PROMPT,
            detail=f"Trust resolved via {resolution.value}",
        )

    def deliver_prompt(self, target: WorkerPromptTarget = WorkerPromptTarget.SHELL) -> bool:
        """Attempt to deliver the prompt to the worker."""
        self.prompt_delivery_attempts += 1

        if target == WorkerPromptTarget.WRONG_TARGET:
            if (
                self.auto_recover_prompt_misdelivery
                and self.prompt_delivery_attempts < self.max_prompt_delivery_attempts
            ):
                self.transition(
                    WorkerStatus.READY_FOR_PROMPT,
                    detail=f"Prompt misdelivered (attempt {self.prompt_delivery_attempts}), retrying",
                )
                return False
            self.transition(
                WorkerStatus.FAILED,
                detail="Prompt misdelivery exceeded max attempts",
            )
            return False

        if target == WorkerPromptTarget.UNKNOWN:
            self.transition(WorkerStatus.FAILED, detail="Unknown prompt target")
            return False

        self.transition(WorkerStatus.RUNNING, detail="Prompt delivered to shell")
        return True

    def finish(self, detail: str = "Completed successfully") -> None:
        self.transition(WorkerStatus.FINISHED, detail=detail)

    def fail(self, kind: WorkerFailureKind, detail: str = "") -> None:
        self.transition(WorkerStatus.FAILED, detail=f"{kind.value}: {detail}")

    def restart(self) -> None:
        """Restart the worker from SPAWNING state."""
        self.trust_gate_cleared = False
        self.prompt_delivery_attempts = 0
        self.transition(WorkerStatus.SPAWNING, detail="Restarted")

    @property
    def is_active(self) -> bool:
        return self.status in (WorkerStatus.RUNNING, WorkerStatus.READY_FOR_PROMPT)

    @property
    def is_terminal(self) -> bool:
        return self.status in (WorkerStatus.FINISHED, WorkerStatus.FAILED)


class WorkerRegistry:
    """Manages multiple worker instances.

    Maps to: rust/crates/runtime/src/worker_boot.rs::WorkerRegistry
    """

    def __init__(self) -> None:
        self._workers: dict[str, Worker] = {}

    def spawn(self, cwd: str = "", **kwargs: Any) -> Worker:
        """Create and register a new worker."""
        worker = Worker(cwd=cwd, **kwargs)
        self._workers[worker.worker_id] = worker
        worker.transition(WorkerStatus.SPAWNING, detail="Worker spawned")
        return worker

    def register(self, worker: Worker) -> None:
        self._workers[worker.worker_id] = worker

    def get(self, worker_id: str) -> Worker | None:
        return self._workers.get(worker_id)

    def all_workers(self) -> list[Worker]:
        return list(self._workers.values())

    def active_workers(self) -> list[Worker]:
        return [w for w in self._workers.values() if w.is_active]

    def finished_workers(self) -> list[Worker]:
        return [w for w in self._workers.values() if w.is_terminal]

    def remove(self, worker_id: str) -> bool:
        return self._workers.pop(worker_id, None) is not None

    def summary(self) -> dict[str, int]:
        """Count workers by status."""
        counts: dict[str, int] = {}
        for worker in self._workers.values():
            counts[worker.status.value] = counts.get(worker.status.value, 0) + 1
        return counts
