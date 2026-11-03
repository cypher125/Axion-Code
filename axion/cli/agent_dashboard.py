"""Live multi-agent dashboard.

One panel in the main terminal that shows every running sub-agent and what each is doing right now,
updating in place — instead of interleaved log lines or (worse) a separate OS window per agent.

On a VT-capable terminal (Windows Terminal, macOS, Linux) it renders a live-updating Rich table. On a
terminal where an in-place redraw would leak escape codes (legacy Windows cmd.exe), it degrades to one
concise line per event — the same information, just scrolling. Either way, each agent also writes its
full transcript to `.axion/agent-logs/<label>.log` so you can open or tail any agent's detail and it
persists after the agent finishes.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.table import Table

from axion.cli.render import rich_live_ok

_STATUS_ICON = {"running": "◉", "done": "✓", "failed": "✗"}


@dataclass
class _AgentRow:
    label: str
    role: str
    action: str = "starting…"
    tokens: int = 0
    status: str = "running"  # running | done | failed


class AgentDashboard:
    """Shared, live view of a fan-out batch of sub-agents. Safe to drive from concurrent async tasks
    (single-threaded event loop). Starts on the first agent, tears down when the last one finishes."""

    def __init__(self, console: Console | None = None) -> None:
        self._console = console or Console()
        self._rows: dict[str, _AgentRow] = {}
        self._order: list[str] = []
        self._active = 0
        self._live: Any | None = None
        self._use_live = rich_live_ok(self._console)

    # -- lifecycle ----------------------------------------------------------------------------
    def register(self, label: str, role: str) -> None:
        if self._active == 0 and self._live is None:
            self._rows.clear()  # fresh fan-out batch
            self._order.clear()
        if label not in self._rows:
            self._rows[label] = _AgentRow(label=label, role=role)
            self._order.append(label)
        else:
            self._rows[label].status = "running"
        self._active += 1
        if self._use_live:
            self._ensure_live()
            self._render()
        else:
            self._line(f"  🔀 [{label}] started ({role})")

    def update(self, label: str, action: str | None = None, tokens: int | None = None) -> None:
        row = self._rows.get(label)
        if row is None:
            return
        if action is not None:
            row.action = action
        if tokens is not None:
            row.tokens = tokens
        if self._use_live:
            self._render()
        elif action:
            self._line(f"    [{label}] {action}")

    def finish(self, label: str, tokens: int = 0, cost: float = 0.0, ok: bool = True, note: str = "") -> None:
        # A finished agent leaves ONE persistent summary line and drops out of the live table (which
        # only ever shows what's still running), so completed agents don't pile up as stale tables.
        icon = _STATUS_ICON["done"] if ok else _STATUS_ICON["failed"]
        extra = f" — {tokens:,} tok" if tokens else ""
        cost_s = f", ${cost:.4f}" if cost else ""
        summary = f"  {icon} {label} — {note or ('done' if ok else 'failed')}{extra}{cost_s}"
        if label in self._rows:
            del self._rows[label]
            self._order.remove(label)
        self._active = max(0, self._active - 1)
        if self._use_live and self._live is not None:
            # Print the summary above the live region (Rich routes console.print above a live display),
            # then shrink the table — or clear it entirely once nothing is running.
            self._line(summary)
            if self._active <= 0 or not self._order:
                self._stop_live()
            else:
                self._render()
        else:
            self._line(summary)

    # -- rendering ----------------------------------------------------------------------------
    def _table(self) -> Table:
        table = Table(title=f"Agents ({len(self._order)} running)", title_justify="left",
                      show_edge=False, pad_edge=False, expand=False)
        table.add_column("", width=1)
        table.add_column("agent", style="cyan", no_wrap=True)
        table.add_column("doing", overflow="ellipsis", max_width=48)
        table.add_column("tokens", justify="right", style="dim")
        for lbl in self._order:
            r = self._rows[lbl]
            table.add_row("◉", r.label, r.action, f"{r.tokens:,}" if r.tokens else "")
        return table

    def _ensure_live(self) -> None:
        if self._live is not None or not self._use_live:
            return
        try:
            from rich.live import Live

            # transient=True: the table vanishes when stopped, leaving only the summary lines — no
            # stack of leftover "0 running" tables.
            self._live = Live(self._table(), console=self._console,
                              refresh_per_second=8, transient=True)
            self._live.start()
        except Exception:
            self._use_live = False
            self._live = None

    def _render(self) -> None:
        if self._live is not None:
            try:
                self._live.update(self._table())
            except Exception:
                pass

    def _stop_live(self) -> None:
        if self._live is not None:
            try:
                self._live.stop()
            except Exception:
                pass
            self._live = None

    def _line(self, text: str) -> None:
        # markup=False so a "[label]" isn't parsed as a Rich style tag (which would drop the label).
        try:
            self._console.print(text, markup=False, highlight=False)
        except Exception:
            sys.stderr.write(text + "\n")
            sys.stderr.flush()


_dashboard: AgentDashboard | None = None


def get_dashboard() -> AgentDashboard:
    """The process-wide dashboard shared by all concurrently-spawned sub-agents."""
    global _dashboard
    if _dashboard is None:
        _dashboard = AgentDashboard()
    return _dashboard
