from hawnan_core.batch_clock import BatchClock
from hawnan_core.estimator import Range, format_range, quantile, range_from_intervals, remaining_range


def test_quantile_interpolates():
    assert quantile([1, 2, 3, 4, 5], 0.5) == 3
    assert quantile([10, 20], 0.2) == 12


def test_range_is_never_a_single_number():
    r = range_from_intervals([480.0] * 8, batches_ahead=1)
    assert r.high_min - r.low_min >= 2
    assert r.about is True
    assert isinstance(r.low_min, int) and isinstance(r.high_min, int)


def test_range_scales_with_batches_ahead_and_uses_p20_p80():
    intervals = [360.0, 420.0, 480.0, 540.0, 600.0]
    r0 = range_from_intervals(intervals, 0)
    r2 = range_from_intervals(intervals, 2)
    assert r0.low_min < r2.low_min and r0.high_min < r2.high_min
    assert r0.basis == "measured"
    # p20 ≈ 408 s → 6 min, p80 ≈ 552 s → 10 min for one batch
    assert (r0.low_min, r0.high_min) == (6, 10)


def test_prior_when_too_few_samples():
    r = range_from_intervals([480.0], 0)
    assert r.basis == "prior" and r.samples == 1
    assert (r.low_min, r.high_min) == (6, 9)


def test_elapsed_time_shrinks_but_keeps_floor():
    intervals = [480.0] * 5
    fresh = range_from_intervals(intervals, 0)
    later = range_from_intervals(intervals, 0, elapsed_in_stage_s=300)
    assert later.low_min < fresh.low_min
    floor = range_from_intervals(intervals, 0, elapsed_in_stage_s=10_000)
    assert floor.low_min >= 1 and floor.high_min > floor.low_min


def test_remaining_range_from_clock_events():
    c = BatchClock()
    c.define_point("W1", "women", 0.0)
    t = 0.0
    for n in range(1, 6):
        bid = f"W1-{n:03d}"
        c.create_batch(bid, "W1", 100.0 * n, 0.0, number=n)
        c.check_in_guest(bid, t + 1)
        c.set_state(bid, "holding", t + 5)
        c.set_state(bid, "prepare", t + 10)
        c.set_state(bid, "moving", t + 20)
        c.record_measurement("W1", bid, "hold", 5.0, t + 10, "simulated")
        t += 480
    c.create_batch("W1-006", "W1", 2000.0, 0.0, number=6)
    c.create_batch("W1-007", "W1", 2480.0, 0.0, number=7)
    c.check_in_guest("W1-007", t)
    c.set_state("W1-007", "holding", t)
    r = remaining_range(c, "W1-007", now=t + 20)
    assert r.basis == "simulated"
    assert r.samples == 4 and r.low_min >= 1 and r.high_min > r.low_min
    assert format_range(r, "about {low}–{high} minutes").startswith("about ")
    done = remaining_range(c, "W1-001", now=t)
    assert done == Range(0, 0, 0, "done", about=False)
