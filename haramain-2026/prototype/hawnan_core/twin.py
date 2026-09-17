"""Digital twin — seeded, deterministic discrete-event simulation.

One day of permits flows through: courtyard arrival → sorting station (permit
check) → holding point (batch) → corridor station → door station → inside the
Rawdah → exit. Batches are driven through the very same ``BatchClock`` used by
the live service, so the numbers on the ops board and the states on a guest's
phone come from one engine.

What the twin lets the Authority compare before touching the field:

* ``checks_per_guest`` = 3 (full permit check at every station) vs 1 (one check,
  then constant-time signed-pass reads at the corridor and the door);
* ``staggered_windows`` on (guests told when to leave, so they arrive shortly
  before their slot) vs off (bus-load bursts at the top of the hour and very
  early arrivals).

Outputs: mean and p90 wait (courtyard arrival → entering the Rawdah), a
pressure-event proxy (minutes in which a station queue grew by more than a
threshold), and the share of batches that entered within their protected
window. Pure Python, no simpy.
"""

from __future__ import annotations

import heapq
import random
from collections import deque
from dataclasses import asdict, dataclass

from .batch_clock import BatchClock
from .estimator import quantile

DAY_START_S = 4 * 3600  # 04:00 local, first slot of the day


@dataclass(frozen=True)
class TwinParams:
    permits_per_day: int = 50_000
    points: int = 4
    checks_per_guest: int = 3  # 1 or 3 (2 = one check + one pass read + one full check)
    check_time_mean_s: float = 20.0
    check_time_sd_s: float = 10.0
    pass_read_s: float = 2.0  # constant-time signed pass read
    staggered_windows: bool = False
    servers_per_station: int = 5
    batch_size: int = 50
    rawdah_capacity: int = 750
    dwell_min: float = 11.0
    protected_minutes: int = 15
    day_hours: float = 18.0
    pressure_threshold: int = 15  # rise of the minute's average queue (guests) counted as a pressure moment
    seed: int = 7

    def validate(self) -> None:
        if not (100 <= self.permits_per_day <= 120_000):
            raise ValueError("permits_per_day must be between 100 and 120000")
        if not (1 <= self.points <= 12):
            raise ValueError("points must be 1..12")
        if self.checks_per_guest not in (1, 2, 3):
            raise ValueError("checks_per_guest must be 1, 2 or 3")
        if self.check_time_mean_s <= 0 or self.check_time_sd_s < 0 or self.pass_read_s <= 0:
            raise ValueError("check times must be positive")
        if not (1 <= self.servers_per_station <= 50):
            raise ValueError("servers_per_station must be 1..50")
        if not (5 <= self.batch_size <= 500):
            raise ValueError("batch_size must be 5..500")
        if self.rawdah_capacity < self.batch_size:
            raise ValueError("rawdah_capacity must hold at least one batch")
        if not (1 <= self.day_hours <= 24) or self.dwell_min <= 0:
            raise ValueError("day_hours/dwell_min out of range")

    @classmethod
    def from_dict(cls, d: dict) -> "TwinParams":
        fields = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        p = cls(**fields)
        p.validate()
        return p


@dataclass(frozen=True)
class TwinResult:
    params: TwinParams
    guests: int
    batches: int
    mean_wait_min: float
    p90_wait_min: float
    max_wait_min: float
    pressure_events: int
    batches_on_time_pct: float
    max_station_queue: int
    mean_hold_min: float
    rebatched_guests: int
    peak_inside: int

    def to_dict(self) -> dict:
        d = asdict(self)
        d["params"] = asdict(self.params)
        return d


class _Station:
    """A check station: FIFO queue + a pool of servers.

    ``area`` integrates queue length over time so the pressure proxy compares
    time-weighted average queue lengths minute by minute, which is immune to
    where in the minute a burst happened to land.
    """

    __slots__ = ("queue", "busy", "servers", "peak", "area", "last_t", "prev_avg")

    def __init__(self, servers: int) -> None:
        self.queue: deque[int] = deque()
        self.busy = 0
        self.servers = servers
        self.peak = 0
        self.area = 0.0
        self.last_t = 0.0
        self.prev_avg = 0.0

    def account(self, now: float) -> None:
        self.area += len(self.queue) * (now - self.last_t)
        self.last_t = now


class _Sim:
    def __init__(self, p: TwinParams) -> None:
        p.validate()
        self.p = p
        self.rng = random.Random(p.seed)
        self.clock = BatchClock()
        self.now = 0.0
        self._seq = 0
        self.heap: list[tuple[float, int, str, int]] = []
        # guests (index-aligned lists)
        self.g_batch: list[str] = []
        self.g_point: list[int] = []
        self.g_arrival: list[float] = []
        self.g_holding_at: list[float] = []
        self.g_entered: list[float] = []
        # batches
        self.b_assigned: dict[str, int] = {}
        self.b_holding: dict[str, int] = {}
        self.b_entered: dict[str, int] = {}
        self.b_left: dict[str, int] = {}
        self.b_released: dict[str, bool] = {}
        self.b_members: dict[str, list[int]] = {}
        self.point_batches: list[list[str]] = [[] for _ in range(p.points)]
        self.point_head: list[int] = [0] * p.points  # index of first unreleased batch
        self.stations: list[list[_Station]] = [
            [_Station(p.servers_per_station) for _ in range(3)] for _ in range(p.points)
        ]
        self.inside = 0  # guests physically inside the Rawdah
        self.committed = 0  # inside + released and on their way in (what a supervisor sees)
        self.pressure_events = 0
        self.peak_inside = 0
        self.max_station_queue = 0
        self.rebatched = 0

    # ---- scheduling ----------------------------------------------------
    def push(self, t: float, kind: str, ref: int) -> None:
        self._seq += 1
        heapq.heappush(self.heap, (t, self._seq, kind, ref))

    def service_time(self, station: int) -> float:
        p = self.p
        full = station < p.checks_per_guest
        if not full:
            return p.pass_read_s
        return max(3.0, self.rng.gauss(p.check_time_mean_s, p.check_time_sd_s))

    # ---- build the day -------------------------------------------------
    def build(self) -> None:
        p = self.p
        per_point = max(1, p.permits_per_day // p.points)
        n_batches = max(1, -(-per_point // p.batch_size))
        interval = p.day_hours * 3600 / n_batches
        for pi in range(p.points):
            lane = "men" if pi % 2 == 0 else "women"
            pid = f"T{pi + 1}"
            self.clock.define_point(pid, lane, 0.0, name_en=f"Twin point {pi + 1}", capacity=p.batch_size * 4)
            for k in range(n_batches):
                bid = f"{pid}-{k + 1:04d}"
                scheduled = DAY_START_S + k * interval
                self.clock.create_batch(bid, pid, scheduled, 0.0, number=k + 1, lane=lane, protected_minutes=p.protected_minutes)
                self.point_batches[pi].append(bid)
                for key in (self.b_assigned, self.b_holding, self.b_entered, self.b_left):
                    key[bid] = 0
                self.b_released[bid] = False
                self.b_members[bid] = []
                self.push(scheduled, "slot", pi)
                size = p.batch_size if k < n_batches - 1 else per_point - p.batch_size * (n_batches - 1)
                for _ in range(max(size, 0)):
                    self._add_guest(bid, pi, scheduled)
        # minute ticks for the pressure proxy
        end = DAY_START_S + p.day_hours * 3600 + 3 * 3600
        t = DAY_START_S - 2 * 3600
        for point_stations in self.stations:
            for st in point_stations:
                st.last_t = t
        while t <= end:
            self.push(t, "tick", 0)
            t += 60.0

    def _add_guest(self, bid: str, pi: int, scheduled: float) -> None:
        p, rng = self.p, self.rng
        if p.staggered_windows:
            arrival = scheduled - 25 * 60 + rng.gauss(0, 6 * 60)
            arrival = max(arrival, scheduled - 60 * 60)
        elif rng.random() < 0.6:
            hour = ((scheduled - 30 * 60) // 3600) * 3600
            arrival = hour + rng.uniform(0, 12 * 60)
        else:
            arrival = scheduled + rng.uniform(-60 * 60, 5 * 60)
        gi = len(self.g_batch)
        self.g_batch.append(bid)
        self.g_point.append(pi)
        self.g_arrival.append(arrival)
        self.g_holding_at.append(-1.0)
        self.g_entered.append(-1.0)
        self.b_assigned[bid] += 1
        self.push(arrival, "arrive", gi)

    # ---- stations ------------------------------------------------------
    def join(self, pi: int, si: int, gi: int) -> None:
        st = self.stations[pi][si]
        if st.busy < st.servers:
            st.busy += 1
            self.push(self.now + self.service_time(si), f"done{si}", gi)
        else:
            st.account(self.now)
            st.queue.append(gi)
            if len(st.queue) > st.peak:
                st.peak = len(st.queue)

    def done(self, pi: int, si: int, gi: int) -> None:
        st = self.stations[pi][si]
        if st.queue:
            st.account(self.now)
            nxt = st.queue.popleft()
            self.push(self.now + self.service_time(si), f"done{si}", nxt)
        else:
            st.busy -= 1
        if si == 0:
            self._reach_holding(pi, gi)
        elif si == 1:
            self.join(pi, 2, gi)
        else:
            self._enter(gi)

    # ---- holding point and batches ------------------------------------
    def _reach_holding(self, pi: int, gi: int) -> None:
        bid = self.g_batch[gi]
        if self.b_released[bid]:  # batch already gone: next unreleased batch takes the guest
            head = self.point_head[pi]
            if head < len(self.point_batches[pi]):
                self.b_assigned[bid] -= 1
                bid = self.point_batches[pi][head]
                self.b_assigned[bid] += 1
                self.g_batch[gi] = bid
                self.rebatched += 1
            else:  # day is over: walk straight through as a late batch member
                self.join(pi, 1, gi)
                return
        batch = self.clock.batches[bid]
        if batch.state == "issued":
            self.clock.set_state(bid, "checked_in", self.now, "twin")
            self.clock.set_state(bid, "holding", self.now, "twin")
        self.b_holding[bid] += 1
        self.b_members[bid].append(gi)
        self.g_holding_at[gi] = self.now
        self.try_release(pi)

    def try_release(self, pi: int) -> None:
        p = self.p
        while self.point_head[pi] < len(self.point_batches[pi]):
            bid = self.point_batches[pi][self.point_head[pi]]
            batch = self.clock.batches[bid]
            if self.now < batch.scheduled_at:
                return
            if batch.state == "issued":  # nobody has arrived yet
                if self.now < batch.scheduled_at + 5 * 60:
                    return
                self.clock.set_state(bid, "checked_in", self.now, "twin")
                self.clock.set_state(bid, "holding", self.now, "twin")
            enough = self.b_holding[bid] >= 0.8 * self.b_assigned[bid]
            if not enough and self.now < batch.scheduled_at + 5 * 60:
                return
            if self.committed + max(self.b_holding[bid], 1) > p.rawdah_capacity:
                return
            self.clock.set_state(bid, "prepare", self.now, "twin")
            self.clock.set_state(bid, "moving", self.now, "twin")
            self.b_released[bid] = True
            self.point_head[pi] += 1
            self.committed += self.b_holding[bid]
            members = self.b_members[bid]
            for gi in members:
                self.join(pi, 1, gi)
            if not members:
                self._close_empty(bid)

    def _close_empty(self, bid: str) -> None:
        self.clock.set_state(bid, "inside", self.now, "twin")
        self.clock.set_state(bid, "exited", self.now, "twin")

    def _enter(self, gi: int) -> None:
        bid = self.g_batch[gi]
        batch = self.clock.batches[bid]
        if batch.state == "moving":
            self.clock.set_state(bid, "inside", self.now, "twin")
        self.b_entered[bid] += 1
        self.inside += 1
        self.g_entered[gi] = self.now
        if self.inside > self.peak_inside:
            self.peak_inside = self.inside
        self.push(self.now + self.p.dwell_min * 60, "leave", gi)

    def _leave(self, gi: int) -> None:
        bid = self.g_batch[gi]
        self.b_left[bid] += 1
        self.inside -= 1
        self.committed -= 1
        if self.b_left[bid] >= self.b_entered[bid] and self.b_left[bid] >= self.b_holding[bid]:
            batch = self.clock.batches[bid]
            if batch.state == "inside":
                self.clock.set_state(bid, "exited", self.now, "twin")
        self.try_release(self.g_point[gi])

    # ---- pressure proxy ------------------------------------------------
    def _tick(self) -> None:
        for point_stations in self.stations:
            for st in point_stations:
                st.account(self.now)
                avg = st.area / 60.0
                st.area = 0.0
                if avg - st.prev_avg > self.p.pressure_threshold:
                    self.pressure_events += 1
                st.prev_avg = avg
                if st.peak > self.max_station_queue:
                    self.max_station_queue = st.peak

    # ---- run -------------------------------------------------------------
    def run(self) -> TwinResult:
        self.build()
        while self.heap:
            t, _, kind, ref = heapq.heappop(self.heap)
            self.now = t
            if kind == "arrive":
                self.join(self.g_point[ref], 0, ref)
            elif kind == "done0":
                self.done(self.g_point[ref], 0, ref)
            elif kind == "done1":
                self.done(self.g_point[ref], 1, ref)
            elif kind == "done2":
                self.done(self.g_point[ref], 2, ref)
            elif kind == "leave":
                self._leave(ref)
            elif kind == "slot":
                self.try_release(ref)
            elif kind == "tick":
                self._tick()
        return self._result()

    def _result(self) -> TwinResult:
        waits = [
            (self.g_entered[i] - self.g_arrival[i]) / 60
            for i in range(len(self.g_batch))
            if self.g_entered[i] >= 0
        ]
        holds = [
            (self.g_entered[i] - self.g_holding_at[i]) / 60
            for i in range(len(self.g_batch))
            if self.g_entered[i] >= 0 and self.g_holding_at[i] >= 0
        ]
        batches = list(self.clock.batches.values())
        judged = [b for b in batches if b.entered_at("inside") is not None and self.b_entered[b.id] > 0]
        on_time = [b for b in judged if (b.entered_at("inside") or 0) <= b.protected_until]
        return TwinResult(
            params=self.p,
            guests=len(self.g_batch),
            batches=len(batches),
            mean_wait_min=round(sum(waits) / len(waits), 1) if waits else 0.0,
            p90_wait_min=round(quantile(waits, 0.9), 1) if waits else 0.0,
            max_wait_min=round(max(waits), 1) if waits else 0.0,
            pressure_events=self.pressure_events,
            batches_on_time_pct=round(100 * len(on_time) / len(judged), 1) if judged else 0.0,
            max_station_queue=self.max_station_queue,
            mean_hold_min=round(sum(holds) / len(holds), 1) if holds else 0.0,
            rebatched_guests=self.rebatched,
            peak_inside=self.peak_inside,
        )


def run(params: TwinParams | dict | None = None) -> TwinResult:
    if params is None:
        params = TwinParams()
    elif isinstance(params, dict):
        params = TwinParams.from_dict(params)
    return _Sim(params).run()


def compare(base: TwinParams | dict | None = None) -> list[dict]:
    """The four scenarios shown on the ops board, same seed and volume."""
    base = TwinParams() if base is None else (TwinParams.from_dict(base) if isinstance(base, dict) else base)
    scenarios = [
        ("3 checks · no windows", dict(checks_per_guest=3, staggered_windows=False)),
        ("1 check · no windows", dict(checks_per_guest=1, staggered_windows=False)),
        ("3 checks · staggered windows", dict(checks_per_guest=3, staggered_windows=True)),
        ("1 check · staggered windows", dict(checks_per_guest=1, staggered_windows=True)),
    ]
    out = []
    for label, overrides in scenarios:
        params = TwinParams(**{**asdict(base), **overrides})
        out.append({"label": label, **run(params).to_dict()})
    return out
