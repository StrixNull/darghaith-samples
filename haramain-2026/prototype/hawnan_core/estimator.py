"""Honest remaining-time ranges.

The estimator never produces a single countdown. It returns a p20–p80 range in
whole minutes, computed from the *measured* release intervals of the last N
batches at the same holding point, multiplied by the number of batches ahead.
When there is not enough data it falls back to a declared prior and says so
in ``basis``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .batch_clock import BatchClock

DEFAULT_INTERVAL_S = (6 * 60, 9 * 60)  # declared prior: 6–9 minutes per batch
MIN_WIDTH_MIN = 2
MIN_SAMPLES = 3


@dataclass(frozen=True)
class Range:
    low_min: int
    high_min: int
    samples: int
    basis: str  # "measured" | "simulated" | "prior"
    about: bool = True  # the semantic is always "about X–Y minutes"

    def to_dict(self) -> dict:
        return {
            "low_min": self.low_min,
            "high_min": self.high_min,
            "samples": self.samples,
            "basis": self.basis,
            "about": self.about,
        }


def quantile(values: list[float], q: float) -> float:
    """Linear-interpolated quantile, q in [0, 1]. Values need not be sorted."""
    if not values:
        raise ValueError("no values")
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    pos = q * (len(xs) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs) - 1)
    frac = pos - lo
    return xs[lo] + (xs[hi] - xs[lo]) * frac


def range_from_intervals(
    intervals_s: list[float],
    batches_ahead: int,
    *,
    elapsed_in_stage_s: float = 0.0,
    basis: str = "measured",
) -> Range:
    """Range for a batch with ``batches_ahead`` batches before it.

    The batch itself also has to be released, so the multiplier is ahead + 1.
    ``elapsed_in_stage_s`` (time already spent waiting since the last release)
    is subtracted so the range shrinks as time passes, never below 1 minute.
    """
    multiplier = max(batches_ahead, 0) + 1
    if len(intervals_s) >= MIN_SAMPLES:
        p20 = quantile(intervals_s, 0.2)
        p80 = quantile(intervals_s, 0.8)
        samples = len(intervals_s)
    else:
        p20, p80 = DEFAULT_INTERVAL_S
        samples = len(intervals_s)
        basis = "prior"
    low_s = max(p20 * multiplier - elapsed_in_stage_s, 60.0)
    high_s = max(p80 * multiplier - elapsed_in_stage_s, low_s)
    low = max(1, int(low_s // 60))
    high = int(-(-high_s // 60))  # ceil
    if high - low < MIN_WIDTH_MIN:
        high = low + MIN_WIDTH_MIN
    return Range(low, high, samples, basis)


def remaining_range(clock: BatchClock, batch_id: str, now: float, *, last_n: int = 8) -> Range:
    """Remaining wait for a batch at its point, from the clock's events only."""
    batch = clock.batches[batch_id]
    if batch.state in ("moving", "inside", "exited"):
        return Range(0, 0, 0, "done", about=False)
    intervals = clock.release_intervals(batch.point_id, last_n=last_n)
    basis = "measured"
    sources = {
        m.source for m in clock.measurements if m.point_id == batch.point_id
    }
    if sources and sources <= {"simulated"}:
        basis = "simulated"
    ahead = clock.position(batch_id)
    last_release = max(
        (b.entered_at("moving") or 0.0 for b in clock.completed(batch.point_id)), default=None
    )
    elapsed = max(0.0, now - last_release) if last_release is not None else 0.0
    return range_from_intervals(intervals, ahead, elapsed_in_stage_s=elapsed, basis=basis)


def format_range(r: Range, template: str) -> str:
    """Render with a language template such as "about {low}–{high} minutes"."""
    return template.format(low=r.low_min, high=r.high_min)
