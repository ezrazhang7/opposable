"""Per-org limits and the abuse signals that trip a suspension.

The framing from HOSTED_PRD §8 is that abuse arrives long before anyone
attempts a VM escape, and that mining and exfiltration each have an obvious
shape. So the controls here are deliberately boring: cap what can run at
once, kill what runs too long, count what leaves, and suspend when a
signature is unmistakable.

Rate limits key on **org and behaviour, never on IP**. Residential proxy
networks rotate through millions of addresses; Cloudflare, GreyNoise and an
FBI/IC3 PSA all land on the same advice — score behaviour, not origin.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class Limits:
    concurrent_tasks: int
    #: Force-stop after this much wall clock. HOSTED_PRD §4: 30 minutes
    #: active, then pause. Stage 0 stops rather than pauses, because pausing
    #: needs the microVM backend.
    wall_clock_seconds: int
    #: Bytes fetched through our egress path in a rolling hour.
    egress_bytes_per_hour: int


PLANS = {
    "free": Limits(concurrent_tasks=1, wall_clock_seconds=30 * 60, egress_bytes_per_hour=512 * 1024**2),
    "paid": Limits(concurrent_tasks=3, wall_clock_seconds=30 * 60, egress_bytes_per_hour=5 * 1024**3),
}

DEFAULT_PLAN = "free"

#: Sustained egress at this rate for a full window is not a research task.
#: Tripping it suspends the account rather than throttling it: exfiltration
#: that is merely slowed down still completes.
SUSPEND_EGRESS_MULTIPLE = 4


def limits_for(plan: str | None) -> Limits:
    return PLANS.get(plan or DEFAULT_PLAN, PLANS[DEFAULT_PLAN])


class QuotaExceeded(RuntimeError):
    """A limit was hit. The message is user-facing."""


class EgressMeter:
    """Rolling one-hour byte counter per org.

    In-process and therefore per-replica, which is honest about what it is:
    Stage 3 moves this to Redis, where the count is global. Until then a
    single API process is the whole deployment, so the number is real.
    """

    WINDOW_SECONDS = 3600

    def __init__(self) -> None:
        self._events: dict[str, list[tuple[float, int]]] = {}
        self._lock = threading.Lock()

    def record(self, org_id: str, byte_count: int) -> int:
        now = time.time()
        cutoff = now - self.WINDOW_SECONDS
        with self._lock:
            events = [e for e in self._events.get(org_id, []) if e[0] >= cutoff]
            events.append((now, byte_count))
            self._events[org_id] = events
            return sum(count for _, count in events)

    def total(self, org_id: str) -> int:
        cutoff = time.time() - self.WINDOW_SECONDS
        with self._lock:
            return sum(c for at, c in self._events.get(org_id, []) if at >= cutoff)


def check_concurrency(running: int, plan: str | None) -> None:
    limit = limits_for(plan).concurrent_tasks
    if running >= limit:
        raise QuotaExceeded(
            f"your plan allows {limit} task{'s' if limit != 1 else ''} at a time; "
            f"stop one before starting another"
        )


def check_egress(total_bytes: int, plan: str | None) -> None:
    limit = limits_for(plan).egress_bytes_per_hour
    if total_bytes > limit:
        raise QuotaExceeded("hourly egress limit reached")


def should_suspend_for_egress(total_bytes: int, plan: str | None) -> bool:
    return total_bytes > limits_for(plan).egress_bytes_per_hour * SUSPEND_EGRESS_MULTIPLE


def overran_wall_clock(started_at: float, plan: str | None, now: float | None = None) -> bool:
    return (now or time.time()) - started_at > limits_for(plan).wall_clock_seconds
