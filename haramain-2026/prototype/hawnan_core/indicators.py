"""Decision-room indicators, from batch events only (no cameras, no persons).

* occupancy per holding point (batches present and checked-in guests present)
* verification throughput per lane (check-ins per minute over a window)
* slowdown alert per point (last release interval vs the recent median)
* share of batches that entered within their protected window
"""

from __future__ import annotations

from .batch_clock import BatchClock
from .estimator import quantile

SLOWDOWN_RATIO = 1.5
DEFAULT_WINDOW_S = 15 * 60


def occupancy(clock: BatchClock, point_id: str) -> dict:
    point = clock.points[point_id]
    present = [b for b in clock.point_batches(point_id) if b.state in ("holding", "prepare")]
    guests = sum(b.guests for b in present)
    return {
        "point_id": point_id,
        "batches_present": len(present),
        "guests_present": guests,
        "capacity": point.capacity,
        "ratio": round(guests / point.capacity, 2) if point.capacity else 0.0,
        "batch_numbers": [b.number for b in present],
    }


def throughput(clock: BatchClock, lane: str, now: float, window_s: int = DEFAULT_WINDOW_S) -> dict:
    since = now - window_s
    n = sum(
        int(e.payload.get("count", 1))
        for e in clock.events
        if e.type == "guest_checked_in" and e.ts >= since and clock.batches[e.batch_id].lane == lane
    )
    return {"lane": lane, "window_s": window_s, "checkins": n, "per_min": round(n / (window_s / 60), 1)}


def slowdown(clock: BatchClock, point_id: str, now: float) -> dict:
    intervals = clock.release_intervals(point_id, last_n=8)
    waiting = [b for b in clock.queue(point_id) if b.state in ("holding", "prepare")]
    releases = [b.entered_at("moving") for b in clock.completed(point_id)]
    last_release = max((t for t in releases if t is not None), default=None)
    if len(intervals) < 3:
        return {"point_id": point_id, "alert": False, "reason": "insufficient_data", "median_interval_s": None, "observed_s": None}
    median = quantile(intervals[:-1], 0.5) if len(intervals) > 3 else quantile(intervals, 0.5)
    observed = intervals[-1]
    stalled = last_release is not None and waiting and (now - last_release) > observed
    if stalled:
        observed = now - last_release
    ratio = observed / median if median else 0.0
    return {
        "point_id": point_id,
        "alert": ratio >= SLOWDOWN_RATIO,
        "reason": "stalled" if stalled and ratio >= SLOWDOWN_RATIO else ("slow_release" if ratio >= SLOWDOWN_RATIO else "normal"),
        "median_interval_s": round(median),
        "observed_s": round(observed),
        "ratio": round(ratio, 2),
    }


def on_time_share(clock: BatchClock, now: float, window_s: int = 3600) -> dict:
    since = now - window_s
    exited = [b for b in clock.batches.values() if b.state == "exited" and (b.entered_at("exited") or 0) >= since]
    on_time = [b for b in exited if (b.entered_at("inside") or float("inf")) <= b.protected_until]
    share = round(100 * len(on_time) / len(exited)) if exited else None
    return {"window_s": window_s, "exited": len(exited), "on_time": len(on_time), "share_pct": share}


def snapshot(clock: BatchClock, now: float) -> dict:
    return {
        "ts": now,
        "points": [
            {**occupancy(clock, pid), "slowdown": slowdown(clock, pid, now), "lane": clock.points[pid].lane, "name_ar": clock.points[pid].name_ar, "name_en": clock.points[pid].name_en}
            for pid in clock.points
        ],
        "throughput": [throughput(clock, lane, now) for lane in ("men", "women")],
        "on_time": on_time_share(clock, now),
        "batches_total": len(clock.batches),
        "events_total": len(clock.events),
    }
