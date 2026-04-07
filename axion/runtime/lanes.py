"""Lane events, branch lock, stale branch detection, and summary compression.

Maps to: rust/crates/runtime/src/lane_events.rs, branch_lock.rs, stale_branch.rs
"""

from __future__ import annotations

import enum
import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Lane status and events
# ---------------------------------------------------------------------------

class LaneStatus(enum.Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    RECONCILED = "reconciled"
    FAILED = "failed"


class LaneEventType(enum.Enum):
    CREATED = "created"
    STARTED = "started"
    TOOL_EXECUTED = "tool_executed"
    ITERATION_COMPLETED = "iteration_completed"
    BLOCKED = "blocked"
    UNBLOCKED = "unblocked"
    GREEN_LEVEL_CHANGED = "green_level_changed"
    REVIEW_REQUESTED = "review_requested"
    REVIEW_APPROVED = "review_approved"
    REVIEW_REJECTED = "review_rejected"
    MERGE_REQUESTED = "merge_requested"
    MERGE_COMPLETED = "merge_completed"
    RECONCILED = "reconciled"
    COMPLETED = "completed"
    FAILED = "failed"
    ESCALATED = "escalated"
    RECOVERED = "recovered"


@dataclass
class LaneEvent:
    """Timestamped event in a lane's lifecycle."""

    lane_id: str
    event_type: LaneEventType
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    details: dict[str, Any] = field(default_factory=dict)
    green_level: int | None = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "lane_id": self.lane_id,
            "event_type": self.event_type.value,
            "timestamp_ms": self.timestamp_ms,
        }
        if self.details:
            d["details"] = self.details
        if self.green_level is not None:
            d["green_level"] = self.green_level
        if self.message:
            d["message"] = self.message
        return d


# ---------------------------------------------------------------------------
# Lane state tracker
# ---------------------------------------------------------------------------

@dataclass
class LaneState:
    """Current state of a lane."""

    lane_id: str
    status: LaneStatus = LaneStatus.ACTIVE
    green_level: int = 0
    branch: str = ""
    worker_id: str | None = None
    events: list[LaneEvent] = field(default_factory=list)
    blocker_reason: str = ""
    created_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    def record_event(
        self,
        event_type: LaneEventType,
        message: str = "",
        **details: Any,
    ) -> LaneEvent:
        event = LaneEvent(
            lane_id=self.lane_id,
            event_type=event_type,
            green_level=self.green_level,
            message=message,
            details=details if details else {},
        )
        self.events.append(event)
        return event


class LaneEventLog:
    """Tracks lane events for git workflow coordination."""

    def __init__(self) -> None:
        self._lanes: dict[str, LaneState] = {}
        self._all_events: list[LaneEvent] = []

    def create_lane(self, lane_id: str, branch: str = "") -> LaneState:
        state = LaneState(lane_id=lane_id, branch=branch)
        state.record_event(LaneEventType.CREATED, f"Lane created for branch {branch}")
        self._lanes[lane_id] = state
        return state

    def get_lane(self, lane_id: str) -> LaneState | None:
        return self._lanes.get(lane_id)

    def record(self, event: LaneEvent) -> None:
        self._all_events.append(event)
        lane = self._lanes.get(event.lane_id)
        if lane:
            lane.events.append(event)

    def events_for_lane(self, lane_id: str) -> list[LaneEvent]:
        lane = self._lanes.get(lane_id)
        return lane.events if lane else []

    def all_events(self) -> list[LaneEvent]:
        return list(self._all_events)

    def all_lanes(self) -> list[LaneState]:
        return list(self._lanes.values())

    def active_lanes(self) -> list[LaneState]:
        return [l for l in self._lanes.values() if l.status == LaneStatus.ACTIVE]


# ---------------------------------------------------------------------------
# Branch lock
# ---------------------------------------------------------------------------

@dataclass
class BranchLock:
    """Lock on a git branch to prevent concurrent modifications."""

    branch: str
    holder: str
    acquired_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    expires_at_ms: int | None = None
    reason: str = ""

    def is_expired(self) -> bool:
        if self.expires_at_ms is None:
            return False
        return int(time.time() * 1000) > self.expires_at_ms


class BranchLockManager:
    """Manages branch locks with expiry and reason tracking."""

    def __init__(self) -> None:
        self._locks: dict[str, BranchLock] = {}

    def acquire(
        self,
        branch: str,
        holder: str,
        ttl_ms: int = 300_000,
        reason: str = "",
    ) -> bool:
        """Acquire a branch lock. Returns False if already held by another."""
        existing = self._locks.get(branch)
        if existing and not existing.is_expired() and existing.holder != holder:
            return False
        now = int(time.time() * 1000)
        self._locks[branch] = BranchLock(
            branch=branch,
            holder=holder,
            acquired_at_ms=now,
            expires_at_ms=now + ttl_ms,
            reason=reason,
        )
        return True

    def release(self, branch: str, holder: str) -> bool:
        lock = self._locks.get(branch)
        if lock and lock.holder == holder:
            del self._locks[branch]
            return True
        return False

    def is_locked(self, branch: str) -> bool:
        lock = self._locks.get(branch)
        return lock is not None and not lock.is_expired()

    def lock_holder(self, branch: str) -> str | None:
        lock = self._locks.get(branch)
        if lock and not lock.is_expired():
            return lock.holder
        return None

    def all_locks(self) -> list[BranchLock]:
        # Clean expired locks
        now = int(time.time() * 1000)
        self._locks = {
            k: v for k, v in self._locks.items()
            if v.expires_at_ms is None or v.expires_at_ms > now
        }
        return list(self._locks.values())


# ---------------------------------------------------------------------------
# Stale branch detection
# ---------------------------------------------------------------------------

DEFAULT_STALE_THRESHOLD_MS = 86_400_000  # 24 hours


def is_stale_branch(
    last_commit_ms: int,
    threshold_ms: int = DEFAULT_STALE_THRESHOLD_MS,
) -> bool:
    """Check if a branch is stale (default: 24 hours since last commit)."""
    now_ms = int(time.time() * 1000)
    return (now_ms - last_commit_ms) > threshold_ms


def branch_freshness_ms(last_commit_ms: int) -> int:
    """Get time since last commit in milliseconds."""
    now_ms = int(time.time() * 1000)
    return now_ms - last_commit_ms


# ---------------------------------------------------------------------------
# Summary compression (for lane event history)
# ---------------------------------------------------------------------------

def compress_lane_summary(events: list[LaneEvent], max_events: int = 20) -> str:
    """Compress a list of lane events into a summary string.

    Keeps the first and last events, plus key transitions.
    """
    if not events:
        return "(no events)"

    if len(events) <= max_events:
        lines = []
        for e in events:
            ts = time.strftime("%H:%M:%S", time.gmtime(e.timestamp_ms / 1000))
            lines.append(f"[{ts}] {e.event_type.value}: {e.message or '(no message)'}")
        return "\n".join(lines)

    # Compress: keep first, last, and key transitions
    key_types = {
        LaneEventType.CREATED, LaneEventType.COMPLETED, LaneEventType.FAILED,
        LaneEventType.BLOCKED, LaneEventType.UNBLOCKED,
        LaneEventType.MERGE_COMPLETED, LaneEventType.ESCALATED,
        LaneEventType.GREEN_LEVEL_CHANGED,
    }

    kept: list[LaneEvent] = [events[0]]
    for e in events[1:-1]:
        if e.event_type in key_types:
            kept.append(e)
    kept.append(events[-1])

    # Truncate if still too long
    if len(kept) > max_events:
        kept = kept[:max_events - 1] + [kept[-1]]

    skipped = len(events) - len(kept)
    lines = []
    for e in kept:
        ts = time.strftime("%H:%M:%S", time.gmtime(e.timestamp_ms / 1000))
        lines.append(f"[{ts}] {e.event_type.value}: {e.message or '(no message)'}")
    if skipped > 0:
        lines.insert(-1, f"  ... ({skipped} events compressed)")

    return "\n".join(lines)
