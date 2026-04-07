"""Task packet, registry, team assignment, and cron scheduling.

Maps to: rust/crates/runtime/src/task_packet.rs + team/cron registries
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Task packet
# ---------------------------------------------------------------------------

@dataclass
class TaskPacket:
    """Specification for an autonomous task."""

    objective: str
    scope: str = ""
    repo: str = ""
    branch_policy: str = "feature-branch"
    acceptance_tests: list[str] = field(default_factory=list)
    commit_policy: str = "atomic"
    reporting_contract: str = ""
    escalation_policy: str = "alert_human"
    priority: int = 0
    tags: list[str] = field(default_factory=list)
    assigned_team: str | None = None
    cron_schedule: str | None = None
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))


@dataclass
class TaskPacketValidationError:
    errors: list[str]


def validate_packet(packet: TaskPacket) -> TaskPacketValidationError | None:
    """Validate a task packet for completeness."""
    errors: list[str] = []
    if not packet.objective:
        errors.append("objective is required")
    if not packet.scope:
        errors.append("scope is required")
    if packet.branch_policy not in ("feature-branch", "direct", "trunk"):
        errors.append(f"invalid branch_policy: {packet.branch_policy}")
    if packet.commit_policy not in ("atomic", "squash", "incremental"):
        errors.append(f"invalid commit_policy: {packet.commit_policy}")
    if packet.escalation_policy not in ("alert_human", "log_and_continue", "abort"):
        errors.append(f"invalid escalation_policy: {packet.escalation_policy}")
    return TaskPacketValidationError(errors=errors) if errors else None


# ---------------------------------------------------------------------------
# Task registry
# ---------------------------------------------------------------------------

class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskEntry:
    """A task in the registry with tracking metadata."""

    task_id: str
    packet: TaskPacket
    status: str = TaskStatus.PENDING
    worker_id: str | None = None
    started_at_ms: int | None = None
    completed_at_ms: int | None = None
    result: str = ""
    error: str = ""


class TaskRegistry:
    """In-memory task lifecycle registry with team assignment and scheduling.

    Maps to: rust/crates/runtime/src/task_packet.rs (registry)
    """

    def __init__(self) -> None:
        self._tasks: dict[str, TaskEntry] = {}
        self._counter = 0

    def create(self, packet: TaskPacket) -> str:
        """Create a new task and return its ID."""
        self._counter += 1
        task_id = f"task-{self._counter:04d}"
        self._tasks[task_id] = TaskEntry(task_id=task_id, packet=packet)
        return task_id

    def get(self, task_id: str) -> TaskEntry | None:
        return self._tasks.get(task_id)

    def all_tasks(self) -> list[TaskEntry]:
        return list(self._tasks.values())

    def pending_tasks(self) -> list[TaskEntry]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

    def running_tasks(self) -> list[TaskEntry]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.RUNNING]

    def start_task(self, task_id: str, worker_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.PENDING:
            return False
        task.status = TaskStatus.RUNNING
        task.worker_id = worker_id
        task.started_at_ms = int(time.time() * 1000)
        return True

    def complete_task(self, task_id: str, result: str = "") -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.RUNNING:
            return False
        task.status = TaskStatus.COMPLETED
        task.result = result
        task.completed_at_ms = int(time.time() * 1000)
        return True

    def fail_task(self, task_id: str, error: str = "") -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status != TaskStatus.RUNNING:
            return False
        task.status = TaskStatus.FAILED
        task.error = error
        task.completed_at_ms = int(time.time() * 1000)
        return True

    def cancel_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if task is None or task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            return False
        task.status = TaskStatus.CANCELLED
        task.completed_at_ms = int(time.time() * 1000)
        return True

    def remove(self, task_id: str) -> bool:
        return self._tasks.pop(task_id, None) is not None

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for task in self._tasks.values():
            counts[task.status] = counts.get(task.status, 0) + 1
        return counts


# ---------------------------------------------------------------------------
# Team registry
# ---------------------------------------------------------------------------

@dataclass
class Team:
    """A named group of workers for task assignment."""

    name: str
    worker_ids: list[str] = field(default_factory=list)
    max_concurrent: int = 1
    tags: list[str] = field(default_factory=list)


class TeamRegistry:
    """Registry of teams for task assignment."""

    def __init__(self) -> None:
        self._teams: dict[str, Team] = {}

    def register(self, team: Team) -> None:
        self._teams[team.name] = team

    def get(self, name: str) -> Team | None:
        return self._teams.get(name)

    def all_teams(self) -> list[Team]:
        return list(self._teams.values())

    def assign_task(self, task: TaskEntry) -> str | None:
        """Find an available team for a task based on tags."""
        for team in self._teams.values():
            if task.packet.assigned_team and task.packet.assigned_team != team.name:
                continue
            # Check tag match
            if task.packet.tags and not any(t in team.tags for t in task.packet.tags):
                continue
            return team.name
        return None


# ---------------------------------------------------------------------------
# Cron registry
# ---------------------------------------------------------------------------

@dataclass
class CronEntry:
    """A scheduled recurring task."""

    cron_id: str
    schedule: str  # Cron expression (e.g. "*/5 * * * *")
    packet: TaskPacket
    enabled: bool = True
    last_run_ms: int = 0
    next_run_ms: int = 0
    run_count: int = 0


class CronRegistry:
    """Registry of cron-scheduled tasks."""

    def __init__(self) -> None:
        self._entries: dict[str, CronEntry] = {}
        self._counter = 0

    def create(self, schedule: str, packet: TaskPacket) -> str:
        self._counter += 1
        cron_id = f"cron-{self._counter:04d}"
        self._entries[cron_id] = CronEntry(
            cron_id=cron_id, schedule=schedule, packet=packet,
        )
        return cron_id

    def get(self, cron_id: str) -> CronEntry | None:
        return self._entries.get(cron_id)

    def all_entries(self) -> list[CronEntry]:
        return list(self._entries.values())

    def enabled_entries(self) -> list[CronEntry]:
        return [e for e in self._entries.values() if e.enabled]

    def enable(self, cron_id: str) -> bool:
        entry = self._entries.get(cron_id)
        if entry is None:
            return False
        entry.enabled = True
        return True

    def disable(self, cron_id: str) -> bool:
        entry = self._entries.get(cron_id)
        if entry is None:
            return False
        entry.enabled = False
        return True

    def remove(self, cron_id: str) -> bool:
        return self._entries.pop(cron_id, None) is not None

    def record_run(self, cron_id: str) -> None:
        entry = self._entries.get(cron_id)
        if entry:
            entry.last_run_ms = int(time.time() * 1000)
            entry.run_count += 1
