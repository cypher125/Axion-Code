"""Tests for task registry, team assignment, and cron scheduling."""

from axion.runtime.tasks import (
    CronRegistry,
    TaskEntry,
    TaskPacket,
    TaskRegistry,
    TaskStatus,
    Team,
    TeamRegistry,
    validate_packet,
)


def test_validate_packet_valid():
    packet = TaskPacket(objective="Fix the bug", scope="src/main.py")
    assert validate_packet(packet) is None


def test_validate_packet_missing_fields():
    packet = TaskPacket(objective="", scope="")
    result = validate_packet(packet)
    assert result is not None
    assert len(result.errors) >= 2


def test_validate_packet_invalid_policy():
    packet = TaskPacket(
        objective="Test", scope="src/",
        branch_policy="invalid",
    )
    result = validate_packet(packet)
    assert result is not None
    assert any("branch_policy" in e for e in result.errors)


def test_task_registry_lifecycle():
    reg = TaskRegistry()
    tid = reg.create(TaskPacket(objective="Fix bug", scope="src/"))

    assert reg.get(tid) is not None
    assert len(reg.pending_tasks()) == 1

    reg.start_task(tid, "worker-1")
    assert len(reg.running_tasks()) == 1
    assert len(reg.pending_tasks()) == 0

    reg.complete_task(tid, result="Fixed")
    task = reg.get(tid)
    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "Fixed"


def test_task_cancel():
    reg = TaskRegistry()
    tid = reg.create(TaskPacket(objective="Test", scope="all"))
    assert reg.cancel_task(tid)
    task = reg.get(tid)
    assert task is not None
    assert task.status == TaskStatus.CANCELLED


def test_task_summary():
    reg = TaskRegistry()
    reg.create(TaskPacket(objective="A", scope="x"))
    reg.create(TaskPacket(objective="B", scope="y"))
    tid3 = reg.create(TaskPacket(objective="C", scope="z"))
    reg.start_task(tid3, "w-1")

    summary = reg.summary()
    assert summary["pending"] == 2
    assert summary["running"] == 1


def test_team_registry():
    reg = TeamRegistry()
    reg.register(Team(name="backend", tags=["rust", "python"]))
    reg.register(Team(name="frontend", tags=["typescript", "react"]))

    assert len(reg.all_teams()) == 2
    assert reg.get("backend") is not None


def test_team_assignment():
    reg = TeamRegistry()
    reg.register(Team(name="backend", tags=["python"]))

    task = TaskEntry(
        task_id="t-1",
        packet=TaskPacket(objective="Fix", scope="src/", tags=["python"]),
    )
    assigned = reg.assign_task(task)
    assert assigned == "backend"


def test_cron_registry():
    reg = CronRegistry()
    cid = reg.create("*/5 * * * *", TaskPacket(objective="Check health", scope="all"))

    assert reg.get(cid) is not None
    assert len(reg.enabled_entries()) == 1

    reg.disable(cid)
    assert len(reg.enabled_entries()) == 0

    reg.enable(cid)
    reg.record_run(cid)
    entry = reg.get(cid)
    assert entry is not None
    assert entry.run_count == 1
