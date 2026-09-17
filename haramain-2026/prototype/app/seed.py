"""A declared SIMULATED permit feed for one demo day.

Four holding points (two men's lanes, two women's lanes), a few hundred
permits with times and a realistic language mix, and measured-looking stage
durations for the batches that already went through, every one of them
flagged ``source="simulated"``. The live UI shows the banner
«بيانات تصاريح محاكاة معلنة» while this feed is active.

This is the ``SimulatedPermitFeed`` of the concept; a ``NusukPermitFeed``
would be built with the Ministry behind the same interface.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from hawnan_core.audit import AuditLog
from hawnan_core.batch_clock import BatchClock

BATCH_INTERVAL_S = 8 * 60
BATCHES_PER_POINT = 24
PAST_BATCHES = 12  # batches 1..12 are already done when the demo starts
PERMITS_PER_BATCH = 12

POINTS: list[dict] = [
    {"id": "M1", "lane": "men", "name_ar": "نقطة الانتظار 1 — الرجال", "name_en": "Holding point 1 — men", "gate_ar": "البوابة 1", "gate_en": "Gate 1", "capacity": 250},
    {"id": "M2", "lane": "men", "name_ar": "نقطة الانتظار 2 — الرجال", "name_en": "Holding point 2 — men", "gate_ar": "البوابة 3", "gate_en": "Gate 3", "capacity": 250},
    {"id": "W1", "lane": "women", "name_ar": "نقطة الانتظار 1 — النساء", "name_en": "Holding point 1 — women", "gate_ar": "البوابة 25", "gate_en": "Gate 25", "capacity": 250},
    {"id": "W2", "lane": "women", "name_ar": "نقطة الانتظار 2 — النساء", "name_en": "Holding point 2 — women", "gate_ar": "البوابة 24", "gate_en": "Gate 24", "capacity": 250},
]
# Language mix of Rawdah visitors (team estimate for the simulation, not a measurement).
LANG_MIX: list[tuple[str, float]] = [
    ("ar", 0.30), ("ur", 0.14), ("id", 0.14), ("en", 0.08), ("bn", 0.08),
    ("tr", 0.07), ("ms", 0.06), ("fr", 0.05), ("ha", 0.04), ("fa", 0.04),
]
HOTEL_AREAS: list[tuple[str, str, int]] = [  # (ar, en, walking distance in metres)
    ("المنطقة المركزية الشمالية", "Central area north", 350),
    ("المنطقة المركزية الجنوبية", "Central area south", 550),
    ("المنطقة الغربية", "West area", 900),
    ("المنطقة الشرقية", "East area", 800),
]
# Memorable refs for the demo script (declared simulated). Siti is the T-24h story.
DEMO_PERMITS: list[tuple[str, str, str]] = [  # (ref, point, lang)
    ("NSK-SITI-0820", "W1", "id"),
    ("NSK-DEMO-UR", "W1", "ur"),
    ("NSK-DEMO-BN", "W1", "bn"),
    ("NSK-DEMO-AR", "M1", "ar"),
    ("NSK-DEMO-EN", "M1", "en"),
    ("NSK-DEMO-TR", "M2", "tr"),
    ("NSK-DEMO-HA", "W2", "ha"),
    ("NSK-DEMO-FA", "W2", "fa"),
]
DEMO_BATCH_NUMBER = PAST_BATCHES + 2  # batch 14: one batch ahead of it is in "prepare"
ANCHOR_OFFSET_S = 7 * 60  # batch 12 released ~1 min before the demo starts
# guests already checked in, by batch offset from the last completed batch
CHECKED_BY_OFFSET = {1: PERMITS_PER_BATCH, 2: PERMITS_PER_BATCH - 4, 3: PERMITS_PER_BATCH - 5, 4: 3}
SIM_INSTRUCTIONS = {"M1": "wait_here", "M2": "please_sit", "W1": "please_sit", "W2": "keep_pass_ready"}


@dataclass(frozen=True)
class SimPermit:
    ref: str
    batch_id: str
    point_id: str
    lane: str
    lang: str
    hotel_area_ar: str
    hotel_area_en: str
    distance_m: int
    checked_in: bool


def _pick_lang(rng: random.Random) -> str:
    x = rng.random()
    acc = 0.0
    for lang, share in LANG_MIX:
        acc += share
        if x < acc:
            return lang
    return "ar"


def build(clock: BatchClock, audit: AuditLog, *, now: float, seed: int = 2026) -> list[SimPermit]:
    """Append the demo day to an empty clock. Returns the simulated permits (plain refs)."""
    rng = random.Random(seed)
    # Batch 12 was released about a minute ago, batch 13 is preparing, batch 14
    # (the demo batch) is holding with one batch ahead of it.
    anchor = now - PAST_BATCHES * BATCH_INTERVAL_S + ANCHOR_OFFSET_S
    permits: list[SimPermit] = []
    for p in POINTS:
        clock.define_point(p["id"], p["lane"], anchor - 3600, name_ar=p["name_ar"], name_en=p["name_en"], gate=p["gate_en"], capacity=p["capacity"], gate_ar=p["gate_ar"])
    demo_by_point: dict[str, list[tuple[str, str]]] = {}
    for ref, pid, lang in DEMO_PERMITS:
        demo_by_point.setdefault(pid, []).append((ref, lang))

    for p in POINTS:
        pid = p["id"]
        for n in range(1, BATCHES_PER_POINT + 1):
            bid = f"{pid}-{n:03d}"
            scheduled = anchor + (n - 1) * BATCH_INTERVAL_S
            clock.create_batch(bid, pid, scheduled, anchor - 3600, number=n, lane=p["lane"], actor="feed:simulated")
            checked = CHECKED_BY_OFFSET.get(n - PAST_BATCHES, PERMITS_PER_BATCH if n <= PAST_BATCHES else 0)
            area = HOTEL_AREAS[rng.randrange(len(HOTEL_AREAS))]
            demo = demo_by_point.get(pid, []) if n == DEMO_BATCH_NUMBER else []
            last_checkin = None
            for k in range(PERMITS_PER_BATCH):
                if k < len(demo):
                    ref, lang = demo[k]
                else:
                    ref = f"NSK-{rng.randrange(10**6):06d}-{pid}{n:02d}"
                    lang = _pick_lang(rng)
                is_checked = k < checked and k >= len(demo)  # demo refs stay unchecked for the presenter
                permits.append(SimPermit(ref, bid, pid, p["lane"], lang, area[0], area[1], area[2] + rng.randrange(-80, 80), is_checked))
                if is_checked:
                    ts = min(scheduled - 25 * 60 + rng.uniform(0, 12 * 60), now - 60 - k * 5)
                    last_checkin = ts if last_checkin is None else max(last_checkin, ts)
                    clock.check_in_guest(bid, ts, lang=lang, actor="feed:simulated")
            if not checked or last_checkin is None:
                continue
            # Measured-looking stage timings (declared simulated), always after the last check-in.
            hold_at = min(max(scheduled - 12 * 60 + rng.uniform(-60, 60), last_checkin + 30), now - 30)
            if n >= PAST_BATCHES + 4:
                continue  # checked_in only
            clock.set_state(bid, "holding", hold_at, "feed:simulated")
            if n >= PAST_BATCHES + 2:
                continue  # holding
            prepare_at = max(scheduled - 6 * 60 + rng.uniform(-60, 60), hold_at + 60)
            if n == PAST_BATCHES + 1:
                clock.set_state(bid, "prepare", min(prepare_at, now - 120), "feed:simulated")
                continue
            release_at = max(scheduled + rng.gauss(30, 60), prepare_at + 60)
            inside_at = release_at + rng.uniform(150, 240)
            exit_at = inside_at + rng.uniform(600, 840)
            clock.set_state(bid, "prepare", prepare_at, "feed:simulated")
            clock.set_state(bid, "moving", release_at, "feed:simulated")
            clock.set_state(bid, "inside", inside_at, "feed:simulated")
            clock.set_state(bid, "exited", exit_at, "feed:simulated")
            for stage, seconds in clock.batches[bid].stage_durations().items():
                clock.record_measurement(pid, bid, stage, round(seconds), exit_at, "simulated")
        clock.set_instruction(pid, SIM_INSTRUCTIONS[pid], now - 90, actor="feed:simulated")
    audit.append("system", "seed", {"feed": "simulated", "points": len(POINTS), "permits": len(permits), "seed": seed}, ts=now)
    return permits
