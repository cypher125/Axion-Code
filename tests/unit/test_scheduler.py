"""Tests for cron scheduler."""

from datetime import datetime

import pytest

from axion.runtime.scheduler import (
    CronScheduler,
    SchedulerConfig,
    cron_matches_now,
    describe_schedule,
)
from axion.runtime.tasks import CronRegistry, TaskPacket, TaskRegistry


def test_cron_every_minute():
    assert cron_matches_now("* * * * *")


def test_cron_specific_minute():
    now = datetime(2026, 4, 7, 14, 30, 0)
    assert cron_matches_now("30 * * * *", now)
    assert not cron_matches_now("15 * * * *", now)


def test_cron_step():
    now = datetime(2026, 4, 7, 14, 0, 0)
    assert cron_matches_now("*/5 * * * *", now)  # 0 % 5 == 0

    now2 = datetime(2026, 4, 7, 14, 3, 0)
    assert not cron_matches_now("*/5 * * * *", now2)  # 3 % 5 != 0


def test_cron_specific_hour_minute():
    now = datetime(2026, 4, 7, 9, 0, 0)
    assert cron_matches_now("0 9 * * *", now)
    assert not cron_matches_now("0 10 * * *", now)


def test_cron_weekday():
    now = datetime(2026, 4, 7, 14, 3, 0)  # Tuesday (weekday=1)
    assert cron_matches_now("* * * * 1", now)  # 1 = Tuesday in Python weekday()
    assert not cron_matches_now("* * * * 0", now)  # 0 = Monday


def test_cron_comma_list():
    now = datetime(2026, 4, 7, 14, 15, 0)
    assert cron_matches_now("0,15,30,45 * * * *", now)
    assert not cron_matches_now("0,10,20,30 * * * *", now)


def test_describe_schedule():
    assert describe_schedule("* * * * *") == "Every minute"
    assert describe_schedule("*/5 * * * *") == "Every 5 minutes"
    assert describe_schedule("0 9 * * *") == "Daily at 9:00"


@pytest.mark.asyncio
async def test_scheduler_start_stop():
    cron_reg = CronRegistry()
    task_reg = TaskRegistry()
    config = SchedulerConfig(check_interval_seconds=0.1)

    scheduler = CronScheduler(cron_reg, task_reg, config)
    await scheduler.start()
    assert scheduler.is_running

    await scheduler.stop()
    assert not scheduler.is_running


@pytest.mark.asyncio
async def test_scheduler_triggers_task():
    cron_reg = CronRegistry()
    task_reg = TaskRegistry()
    triggered: list[str] = []

    # Create a cron entry that matches every minute
    cron_reg.create("* * * * *", TaskPacket(objective="Test task", scope="all"))

    async def on_trigger(task_id: str, packet: TaskPacket) -> None:
        triggered.append(task_id)

    scheduler = CronScheduler(
        cron_reg, task_reg,
        config=SchedulerConfig(check_interval_seconds=0.1),
        on_task_triggered=on_trigger,
    )

    # Manually trigger a check
    await scheduler._check_and_trigger()

    assert len(triggered) == 1
    assert len(task_reg.all_tasks()) == 1


def test_scheduler_status():
    cron_reg = CronRegistry()
    task_reg = TaskRegistry()
    cron_reg.create("*/5 * * * *", TaskPacket(objective="Health check", scope="all"))

    scheduler = CronScheduler(cron_reg, task_reg)
    status = scheduler.status()

    assert status["running"] is False
    assert status["total_entries"] == 1
    assert status["enabled_entries"] == 1
