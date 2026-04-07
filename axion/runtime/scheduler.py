"""Cron scheduler loop — runs scheduled tasks on a timer.

Checks the CronRegistry every minute and triggers due tasks by
creating entries in the TaskRegistry and optionally spawning workers.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from axion.runtime.tasks import CronRegistry, TaskPacket, TaskRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Cron expression parser (basic: minute hour day month weekday)
# ---------------------------------------------------------------------------

def cron_matches_now(expression: str, now: datetime | None = None) -> bool:
    """Check if a cron expression matches the current (or given) time.

    Supports: * (any), specific values, comma-separated lists, and */N (step).
    Format: minute hour day_of_month month day_of_week
    """
    now = now or datetime.now()
    parts = expression.strip().split()
    if len(parts) != 5:
        logger.warning("Invalid cron expression (need 5 fields): %s", expression)
        return False

    fields = [
        (parts[0], now.minute, 0, 59),
        (parts[1], now.hour, 0, 23),
        (parts[2], now.day, 1, 31),
        (parts[3], now.month, 1, 12),
        (parts[4], now.weekday(), 0, 6),  # 0=Monday in Python
    ]

    for pattern, current, low, high in fields:
        if not _field_matches(pattern, current, low, high):
            return False
    return True


def _field_matches(pattern: str, value: int, low: int, high: int) -> bool:
    """Check if a single cron field matches the current value."""
    if pattern == "*":
        return True

    # Step: */N
    step_match = re.match(r"^\*/(\d+)$", pattern)
    if step_match:
        step = int(step_match.group(1))
        return value % step == 0

    # Comma-separated list: 1,5,10
    for part in pattern.split(","):
        part = part.strip()
        # Range: 1-5
        range_match = re.match(r"^(\d+)-(\d+)$", part)
        if range_match:
            lo, hi = int(range_match.group(1)), int(range_match.group(2))
            if lo <= value <= hi:
                return True
            continue
        # Exact value
        try:
            if int(part) == value:
                return True
        except ValueError:
            pass

    return False


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

@dataclass
class SchedulerConfig:
    """Configuration for the cron scheduler."""

    check_interval_seconds: float = 60.0  # Check every minute
    max_concurrent_tasks: int = 5
    enabled: bool = True


class CronScheduler:
    """Background scheduler that triggers cron-scheduled tasks.

    Usage:
        scheduler = CronScheduler(cron_registry, task_registry)
        await scheduler.start()
        # ... later ...
        await scheduler.stop()
    """

    def __init__(
        self,
        cron_registry: CronRegistry,
        task_registry: TaskRegistry,
        config: SchedulerConfig | None = None,
        on_task_triggered: Callable[[str, TaskPacket], Awaitable[None]] | None = None,
    ) -> None:
        self.cron_registry = cron_registry
        self.task_registry = task_registry
        self.config = config or SchedulerConfig()
        self.on_task_triggered = on_task_triggered
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the scheduler loop in the background."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Cron scheduler started (interval: %.0fs)", self.config.check_interval_seconds)

    async def stop(self) -> None:
        """Stop the scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Cron scheduler stopped")

    @property
    def is_running(self) -> bool:
        return self._running

    async def _loop(self) -> None:
        """Main scheduler loop — checks cron entries every interval."""
        while self._running:
            try:
                await self._check_and_trigger()
            except Exception:
                logger.exception("Scheduler loop error")

            await asyncio.sleep(self.config.check_interval_seconds)

    async def _check_and_trigger(self) -> None:
        """Check all enabled cron entries and trigger any that are due."""
        now = datetime.now()
        now_ms = int(time.time() * 1000)

        for entry in self.cron_registry.enabled_entries():
            if not cron_matches_now(entry.schedule, now):
                continue

            # Don't re-trigger within the same minute
            if entry.last_run_ms > 0:
                elapsed_ms = now_ms - entry.last_run_ms
                if elapsed_ms < 55_000:  # Less than 55 seconds since last run
                    continue

            # Trigger the task
            logger.info("Cron trigger: %s (schedule: %s)", entry.cron_id, entry.schedule)
            task_id = self.task_registry.create(entry.packet)
            self.cron_registry.record_run(entry.cron_id)

            # Notify callback if set
            if self.on_task_triggered:
                try:
                    await self.on_task_triggered(task_id, entry.packet)
                except Exception:
                    logger.exception("on_task_triggered callback failed for %s", task_id)

    def status(self) -> dict[str, Any]:
        """Return scheduler status summary."""
        entries = self.cron_registry.all_entries()
        return {
            "running": self._running,
            "interval_seconds": self.config.check_interval_seconds,
            "total_entries": len(entries),
            "enabled_entries": len([e for e in entries if e.enabled]),
            "entries": [
                {
                    "cron_id": e.cron_id,
                    "schedule": e.schedule,
                    "enabled": e.enabled,
                    "run_count": e.run_count,
                    "last_run_ms": e.last_run_ms,
                    "objective": e.packet.objective[:50],
                }
                for e in entries
            ],
        }


# ---------------------------------------------------------------------------
# Convenience: human-readable schedule descriptions
# ---------------------------------------------------------------------------

def describe_schedule(expression: str) -> str:
    """Convert a cron expression to a human-readable description."""
    parts = expression.strip().split()
    if len(parts) != 5:
        return expression

    minute, hour, dom, month, dow = parts

    if expression == "* * * * *":
        return "Every minute"
    if minute.startswith("*/"):
        n = minute[2:]
        return f"Every {n} minutes"
    if hour == "*" and minute != "*":
        return f"Every hour at minute {minute}"
    if dom == "*" and month == "*" and dow == "*":
        if hour != "*" and minute != "*":
            return f"Daily at {hour}:{minute.zfill(2)}"
    if dow != "*" and dom == "*":
        days = {"0": "Mon", "1": "Tue", "2": "Wed", "3": "Thu", "4": "Fri", "5": "Sat", "6": "Sun"}
        day_name = days.get(dow, dow)
        if hour != "*" and minute != "*":
            return f"Every {day_name} at {hour}:{minute.zfill(2)}"

    return expression
