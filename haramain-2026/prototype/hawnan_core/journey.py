"""Journey messages: T-24h, T-90min and T-30min, per language and gate.

The departure time is computed for an elderly walking pace plus a buffer for
the sorting point, so the message can honestly say "leave at 07:15".
Times are rendered with Western digits in Madinah local time.
"""

from __future__ import annotations

from dataclasses import dataclass

ELDERLY_SPEED_M_PER_MIN = 45.0  # ≈ 0.75 m/s, unhurried pace with pauses
SORTING_BUFFER_MIN = 20  # time to reach the holding point through the sorting point
MADINAH_UTC_OFFSET_H = 3
PLACEHOLDERS: tuple[str, ...] = ("slot", "depart", "gate", "point", "batch", "walk_min", "hotel_area")


class JourneyError(ValueError):
    pass


@dataclass(frozen=True)
class JourneyInput:
    batch_number: int
    scheduled_at: float  # epoch seconds
    gate: str
    point_name: str
    hotel_area: str
    distance_m: float
    walking_speed_m_per_min: float = ELDERLY_SPEED_M_PER_MIN
    buffer_min: int = SORTING_BUFFER_MIN
    utc_offset_h: int = MADINAH_UTC_OFFSET_H


def walk_minutes(distance_m: float, speed: float = ELDERLY_SPEED_M_PER_MIN) -> int:
    if distance_m < 0 or speed <= 0:
        raise JourneyError("distance and speed must be positive")
    return int(-(-distance_m // speed))  # ceil


def departure_time(inp: JourneyInput) -> float:
    return inp.scheduled_at - (walk_minutes(inp.distance_m, inp.walking_speed_m_per_min) + inp.buffer_min) * 60


def fmt_hhmm(epoch: float, utc_offset_h: int = MADINAH_UTC_OFFSET_H) -> str:
    """HH:MM with Western digits, no locale involved."""
    local = int(epoch) + utc_offset_h * 3600
    minutes = (local % 86400) // 60
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def render(templates: dict, inp: JourneyInput) -> dict:
    """Fill the pack's templates. Missing placeholders in a template are a pack bug."""
    values = {
        "slot": fmt_hhmm(inp.scheduled_at, inp.utc_offset_h),
        "depart": fmt_hhmm(departure_time(inp), inp.utc_offset_h),
        "gate": inp.gate,
        "point": inp.point_name,
        "batch": str(inp.batch_number),
        "walk_min": str(walk_minutes(inp.distance_m, inp.walking_speed_m_per_min)),
        "hotel_area": inp.hotel_area,
    }
    out: dict = {}
    for key in ("t24", "t90", "t30"):
        template = templates.get(key)
        if not template:
            raise JourneyError(f"journey template {key!r} missing")
        try:
            out[key] = template.format_map(values)
        except (KeyError, IndexError, ValueError) as exc:
            raise JourneyError(f"bad placeholder in template {key!r}: {exc}") from exc
    out["protected_note"] = templates.get("protected_note", "")
    out["slot"] = values["slot"]
    out["depart"] = values["depart"]
    out["walk_min"] = int(values["walk_min"])
    return out
