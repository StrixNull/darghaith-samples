from hawnan_core.batch_clock import BatchClock
from hawnan_core.indicators import occupancy, on_time_share, slowdown, snapshot, throughput


def build(now=10_000.0, stall=False):
    """Five completed batches released every 8 min; the last release was 100 s ago.

    With ``stall`` the last release came 900 s late (interval 1380 s instead of 480 s).
    """
    c = BatchClock()
    c.define_point("M1", "men", 0.0, capacity=100)
    c.define_point("W1", "women", 0.0, capacity=100)
    delay = 900 if stall else 0
    t = now - 100 - 4 * 480 - delay
    for n in range(1, 6):
        bid = f"M1-{n:03d}"
        release = t + (delay if n == 5 else 0)
        c.create_batch(bid, "M1", t - 30, 0.0, number=n, protected_minutes=15)
        for _ in range(10):
            c.check_in_guest(bid, t - 1500, lang="ur")
        c.set_state(bid, "holding", t - 50)
        c.set_state(bid, "prepare", t - 20)
        c.set_state(bid, "moving", release)
        c.set_state(bid, "inside", release + 60)
        c.set_state(bid, "exited", release + 600)
        t += 480
    c.create_batch("M1-006", "M1", now + 300, 0.0, number=6)
    for _ in range(25):
        c.check_in_guest("M1-006", now - 60, lang="id")
    c.set_state("M1-006", "holding", now - 30)
    c.create_batch("W1-001", "W1", now, 0.0, number=1)
    c.check_in_guest("W1-001", now - 10, lang="bn")
    return c


def test_occupancy_counts_batches_and_guests_present():
    c = build()
    occ = occupancy(c, "M1")
    assert occ["batches_present"] == 1 and occ["guests_present"] == 25 and occ["ratio"] == 0.25
    assert occ["batch_numbers"] == [6]


def test_throughput_per_lane_in_window():
    c = build(now=10_000.0)
    men = throughput(c, "men", now=10_000.0, window_s=600)
    women = throughput(c, "women", now=10_000.0, window_s=600)
    assert men["checkins"] == 25 and men["per_min"] == 2.5
    assert women["checkins"] == 1


def test_slowdown_alert_fires_on_slow_release():
    normal = slowdown(build(), "M1", now=10_000.0)
    assert normal["alert"] is False and normal["reason"] == "normal"
    slow = slowdown(build(stall=True), "M1", now=10_000.0)
    assert slow["alert"] is True and slow["ratio"] >= 1.5


def test_on_time_share_and_snapshot():
    c = build()
    share = on_time_share(c, now=10_000.0, window_s=4000)
    assert share["exited"] >= 1 and share["share_pct"] == 100
    late = on_time_share(build(stall=True), now=10_000.0, window_s=4000)
    assert late["share_pct"] < 100
    snap = snapshot(c, now=10_000.0)
    assert {p["point_id"] for p in snap["points"]} == {"M1", "W1"}
    assert snap["batches_total"] == 7
