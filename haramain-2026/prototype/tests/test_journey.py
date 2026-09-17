import json
from pathlib import Path

import pytest

from hawnan_core.journey import JourneyError, JourneyInput, departure_time, fmt_hhmm, render, walk_minutes

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
# 2026-09-18 08:20 Madinah (UTC+3) = 05:20 UTC
SLOT = 1_789_618_800.0 + 0  # placeholder, replaced below


def _slot():
    import calendar
    return float(calendar.timegm((2026, 9, 18, 5, 20, 0)))


def test_departure_for_elderly_pace():
    inp = JourneyInput(14, _slot(), "Gate 25", "Point W1", "Central north", distance_m=900)
    assert walk_minutes(900) == 20  # 900 m at 45 m/min
    assert fmt_hhmm(_slot()) == "08:20"
    assert fmt_hhmm(departure_time(inp)) == "07:40"  # 20 min walk + 20 min buffer


@pytest.mark.parametrize("lang", ["ar", "en", "ur", "id", "tr", "bn", "fr", "ms", "ha", "fa"])
def test_render_every_language(lang):
    pack = json.loads((CONTENT_DIR / f"{lang}.json").read_text(encoding="utf-8"))
    inp = JourneyInput(14, _slot(), "Gate 25", "Point W1", "Central north", distance_m=900)
    out = render(pack["journey"], inp)
    for key in ("t24", "t90", "t30"):
        assert "{" not in out[key] and "08:20" in out[key]
    assert "07:40" in out["t24"] and "Gate 25" in out["t24"] and "Point W1" in out["t24"]
    assert out["walk_min"] == 20 and out["protected_note"]


def test_bad_template_is_a_pack_error():
    inp = JourneyInput(1, _slot(), "G", "P", "H", 100)
    with pytest.raises(JourneyError):
        render({"t24": "{nope}", "t90": "x", "t30": "y"}, inp)
    with pytest.raises(JourneyError):
        render({"t24": "x", "t90": "y"}, inp)
