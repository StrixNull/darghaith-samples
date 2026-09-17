"""Batch Clock — event-sourced state machine for batches and holding points.

State is never stored; it is a fold over an append-only list of events.
The live service, the displays, the indicators and the digital twin all use
this module, so they can never disagree about what a batch is doing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

STATES: tuple[str, ...] = (
    "issued",
    "checked_in",
    "holding",
    "prepare",
    "moving",
    "inside",
    "exited",
)
LANES: tuple[str, ...] = ("men", "women")

# Linear flow: each state may only advance to the next one.
NEXT_STATE: dict[str, str | None] = {
    s: (STATES[i + 1] if i + 1 < len(STATES) else None) for i, s in enumerate(STATES)
}
# Stages measured for the estimator: (from_state, to_state) → stage name.
STAGES: dict[tuple[str, str], str] = {
    ("checked_in", "holding"): "check_to_hold",
    ("holding", "prepare"): "hold",
    ("prepare", "moving"): "prepare",
    ("moving", "inside"): "move",
    ("inside", "exited"): "inside",
}

EVENT_TYPES: tuple[str, ...] = (
    "point_defined",
    "batch_created",
    "guest_checked_in",
    "batch_state",
    "instruction_set",
    "instruction_cleared",
    "measurement",
)


class ClockError(ValueError):
    """Base error for the batch clock."""


class InvalidTransition(ClockError):
    """Raised when an event would move a batch against the flow."""


class UnknownBatch(ClockError):
    """Raised when an event references a batch that was never created."""


@dataclass(frozen=True)
class Event:
    """One immutable fact. ``ts`` is epoch seconds (float)."""

    ts: float
    type: str
    batch_id: str
    point_id: str
    payload: dict = field(default_factory=dict)
    actor: str = "system"

    def to_dict(self) -> dict:
        return {
            "ts": self.ts,
            "type": self.type,
            "batch_id": self.batch_id,
            "point_id": self.point_id,
            "payload": dict(self.payload),
            "actor": self.actor,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            ts=float(d["ts"]),
            type=str(d["type"]),
            batch_id=str(d.get("batch_id", "")),
            point_id=str(d.get("point_id", "")),
            payload=dict(d.get("payload") or {}),
            actor=str(d.get("actor", "system")),
        )


@dataclass
class Batch:
    id: str
    number: int
    point_id: str
    lane: str
    scheduled_at: float
    protected_until: float
    state: str = "issued"
    created_at: float = 0.0
    guests: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    # (state, ts) in the order they were entered, starting with "issued".
    history: list[tuple[str, float]] = field(default_factory=list)

    def entered_at(self, state: str) -> float | None:
        for s, ts in self.history:
            if s == state:
                return ts
        return None

    @property
    def is_done(self) -> bool:
        return self.state == "exited"

    @property
    def is_active(self) -> bool:
        """Batch is physically present at the holding point or beyond, not yet out."""
        return self.state in ("holding", "prepare", "moving", "inside")

    def stage_durations(self) -> dict[str, float]:
        """Seconds spent in each measured stage, from the history alone."""
        out: dict[str, float] = {}
        for (a, b), name in STAGES.items():
            ta, tb = self.entered_at(a), self.entered_at(b)
            if ta is not None and tb is not None and tb >= ta:
                out[name] = tb - ta
        return out

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "number": self.number,
            "point_id": self.point_id,
            "lane": self.lane,
            "scheduled_at": self.scheduled_at,
            "protected_until": self.protected_until,
            "state": self.state,
            "guests": self.guests,
            "languages": dict(self.languages),
            "history": [{"state": s, "ts": ts} for s, ts in self.history],
        }


@dataclass
class Point:
    id: str
    lane: str
    name_ar: str = ""
    name_en: str = ""
    gate: str = ""
    capacity: int = 200
    active_instruction_id: str | None = None
    instruction_set_at: float | None = None
    instruction_seq: int = 0
    batch_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "lane": self.lane,
            "name_ar": self.name_ar,
            "name_en": self.name_en,
            "gate": self.gate,
            "capacity": self.capacity,
            "active_instruction_id": self.active_instruction_id,
            "instruction_set_at": self.instruction_set_at,
            "instruction_seq": self.instruction_seq,
        }


@dataclass
class Measurement:
    point_id: str
    batch_id: str
    stage: str
    seconds: float
    source: str  # "field" | "simulated"


class BatchClock:
    """Mutable fold over an append-only event list.

    ``apply`` validates and applies one event. ``fold`` rebuilds a clock from
    stored events. Producer helpers (``create_batch``, ``advance``...) build a
    valid event, apply it and return it so the caller can persist it.
    """

    def __init__(self) -> None:
        self.events: list[Event] = []
        self.batches: dict[str, Batch] = {}
        self.points: dict[str, Point] = {}
        self.measurements: list[Measurement] = []

    # ---- folding -------------------------------------------------------
    @classmethod
    def fold(cls, events: Iterable[Event]) -> "BatchClock":
        clock = cls()
        for ev in events:
            clock.apply(ev)
        return clock

    def apply(self, ev: Event) -> Event:
        handler = getattr(self, f"_on_{ev.type}", None)
        if handler is None:
            raise ClockError(f"unknown event type: {ev.type}")
        handler(ev)
        self.events.append(ev)
        return ev

    def _on_point_defined(self, ev: Event) -> None:
        p = ev.payload
        lane = p.get("lane", "men")
        if lane not in LANES:
            raise ClockError(f"unknown lane: {lane}")
        point = self.points.get(ev.point_id) or Point(id=ev.point_id, lane=lane)
        point.lane = lane
        point.name_ar = p.get("name_ar", point.name_ar)
        point.name_en = p.get("name_en", point.name_en)
        point.gate = p.get("gate", point.gate)
        point.capacity = int(p.get("capacity", point.capacity))
        self.points[ev.point_id] = point

    def _on_batch_created(self, ev: Event) -> None:
        if ev.batch_id in self.batches:
            raise ClockError(f"batch already exists: {ev.batch_id}")
        if ev.point_id not in self.points:
            raise ClockError(f"unknown point: {ev.point_id}")
        p = ev.payload
        lane = p.get("lane") or self.points[ev.point_id].lane
        if lane not in LANES:
            raise ClockError(f"unknown lane: {lane}")
        scheduled_at = float(p["scheduled_at"])
        protected_until = float(p.get("protected_until", scheduled_at + 15 * 60))
        batch = Batch(
            id=ev.batch_id,
            number=int(p.get("number", len(self.points[ev.point_id].batch_ids) + 1)),
            point_id=ev.point_id,
            lane=lane,
            scheduled_at=scheduled_at,
            protected_until=protected_until,
            created_at=ev.ts,
            history=[("issued", ev.ts)],
        )
        self.batches[ev.batch_id] = batch
        self.points[ev.point_id].batch_ids.append(ev.batch_id)

    def _on_guest_checked_in(self, ev: Event) -> None:
        batch = self._batch(ev.batch_id)
        if batch.state not in ("issued", "checked_in", "holding"):
            raise InvalidTransition(
                f"batch {batch.id} is {batch.state}; check-in closed"
            )
        batch.guests += int(ev.payload.get("count", 1))
        lang = ev.payload.get("lang")
        if lang:
            batch.languages[lang] = batch.languages.get(lang, 0) + 1
        if batch.state == "issued":
            batch.state = "checked_in"
            batch.history.append(("checked_in", ev.ts))

    def _on_batch_state(self, ev: Event) -> None:
        batch = self._batch(ev.batch_id)
        to_state = ev.payload.get("state")
        if to_state not in STATES:
            raise InvalidTransition(f"unknown state: {to_state}")
        if NEXT_STATE[batch.state] != to_state:
            raise InvalidTransition(
                f"batch {batch.id}: {batch.state} → {to_state} is not allowed"
            )
        last_ts = batch.history[-1][1] if batch.history else batch.created_at
        if ev.ts < last_ts:
            raise InvalidTransition("event timestamp goes backwards")
        batch.state = to_state
        batch.history.append((to_state, ev.ts))

    def _on_instruction_set(self, ev: Event) -> None:
        point = self._point(ev.point_id)
        point.active_instruction_id = str(ev.payload["instruction_id"])
        point.instruction_set_at = ev.ts
        point.instruction_seq += 1

    def _on_instruction_cleared(self, ev: Event) -> None:
        point = self._point(ev.point_id)
        point.active_instruction_id = None
        point.instruction_set_at = ev.ts
        point.instruction_seq += 1

    def _on_measurement(self, ev: Event) -> None:
        p = ev.payload
        self.measurements.append(
            Measurement(
                point_id=ev.point_id,
                batch_id=ev.batch_id,
                stage=str(p["stage"]),
                seconds=float(p["seconds"]),
                source=str(p.get("source", "simulated")),
            )
        )

    # ---- producers -----------------------------------------------------
    def define_point(self, point_id: str, lane: str, ts: float, **attrs) -> Event:
        return self.apply(
            Event(ts, "point_defined", "", point_id, {"lane": lane, **attrs})
        )

    def create_batch(
        self,
        batch_id: str,
        point_id: str,
        scheduled_at: float,
        ts: float,
        *,
        number: int | None = None,
        lane: str | None = None,
        protected_minutes: int = 15,
        actor: str = "system",
    ) -> Event:
        payload = {
            "scheduled_at": scheduled_at,
            "protected_until": scheduled_at + protected_minutes * 60,
        }
        if number is not None:
            payload["number"] = number
        if lane is not None:
            payload["lane"] = lane
        return self.apply(Event(ts, "batch_created", batch_id, point_id, payload, actor))

    def check_in_guest(
        self, batch_id: str, ts: float, *, lang: str | None = None, actor: str = "checkin"
    ) -> Event:
        batch = self._batch(batch_id)
        payload = {"count": 1}
        if lang:
            payload["lang"] = lang
        return self.apply(
            Event(ts, "guest_checked_in", batch_id, batch.point_id, payload, actor)
        )

    def set_state(self, batch_id: str, state: str, ts: float, actor: str = "system") -> Event:
        batch = self._batch(batch_id)
        return self.apply(
            Event(ts, "batch_state", batch_id, batch.point_id, {"state": state}, actor)
        )

    def advance(self, batch_id: str, ts: float, actor: str = "supervisor") -> Event:
        batch = self._batch(batch_id)
        nxt = NEXT_STATE[batch.state]
        if nxt is None:
            raise InvalidTransition(f"batch {batch.id} already exited")
        return self.set_state(batch_id, nxt, ts, actor)

    def set_instruction(
        self, point_id: str, instruction_id: str, ts: float, actor: str = "supervisor"
    ) -> Event:
        return self.apply(
            Event(ts, "instruction_set", "", point_id, {"instruction_id": instruction_id}, actor)
        )

    def clear_instruction(self, point_id: str, ts: float, actor: str = "supervisor") -> Event:
        return self.apply(Event(ts, "instruction_cleared", "", point_id, {}, actor))

    def record_measurement(
        self, point_id: str, batch_id: str, stage: str, seconds: float, ts: float, source: str
    ) -> Event:
        return self.apply(
            Event(
                ts,
                "measurement",
                batch_id,
                point_id,
                {"stage": stage, "seconds": seconds, "source": source},
            )
        )

    # ---- queries -------------------------------------------------------
    def _batch(self, batch_id: str) -> Batch:
        try:
            return self.batches[batch_id]
        except KeyError as exc:
            raise UnknownBatch(batch_id) from exc

    def _point(self, point_id: str) -> Point:
        try:
            return self.points[point_id]
        except KeyError as exc:
            raise ClockError(f"unknown point: {point_id}") from exc

    def point_batches(self, point_id: str) -> list[Batch]:
        point = self._point(point_id)
        return sorted(
            (self.batches[b] for b in point.batch_ids), key=lambda b: (b.scheduled_at, b.number)
        )

    def queue(self, point_id: str) -> list[Batch]:
        """Batches not yet moving, in release order."""
        return [b for b in self.point_batches(point_id) if b.state in ("issued", "checked_in", "holding", "prepare")]

    def position(self, batch_id: str) -> int:
        """How many batches are ahead of this one at its point (0 = next to move)."""
        batch = self._batch(batch_id)
        ahead = 0
        for b in self.queue(batch.point_id):
            if b.id == batch_id:
                return ahead
            ahead += 1
        return 0

    def completed(self, point_id: str, last_n: int | None = None) -> list[Batch]:
        done = [b for b in self.point_batches(point_id) if b.entered_at("moving") is not None]
        done.sort(key=lambda b: b.entered_at("moving") or 0.0)
        return done[-last_n:] if last_n else done

    def release_intervals(self, point_id: str, last_n: int = 8) -> list[float]:
        """Seconds between consecutive batch releases (entry into ``moving``)."""
        done = self.completed(point_id)
        times = [b.entered_at("moving") or 0.0 for b in done]
        gaps = [b - a for a, b in zip(times, times[1:]) if b >= a]
        return gaps[-last_n:]
