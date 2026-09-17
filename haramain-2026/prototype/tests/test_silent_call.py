import pytest

from hawnan_core.silent_call import BY_ID, CATALOGUE, LANGS, SilentCall, SilentCallError

TEXTS = {
    "ar": {i.id: f"ar-{i.id}" for i in CATALOGUE},
    "en": {i.id: f"en-{i.id}" for i in CATALOGUE},
    "id": {i.id: f"id-{i.id}" for i in CATALOGUE},
}


def test_catalogue_has_twenty_stable_ids_with_pictograms():
    assert len(CATALOGUE) == 20
    assert len({i.id for i in CATALOGUE}) == 20
    assert all(i.pictogram and i.icon_name for i in CATALOGUE)
    assert BY_ID["no_photography"].forbidden is True
    assert len(LANGS) == 10


def test_single_active_instruction_per_point_and_history():
    sc = SilentCall(TEXTS)
    b1 = sc.broadcast("W1", "please_sit", actor="sup", ts=1.0, languages_present={"id": 5, "ur": 2})
    b2 = sc.broadcast("W1", "advance_calmly", actor="sup", ts=2.0, languages_present={"id": 5})
    sc.broadcast("M1", "wait_here", actor="sup", ts=3.0)
    assert sc.active["W1"] is b2 and sc.active["W1"].instruction_id == "advance_calmly"
    assert sc.active["M1"].instruction_id == "wait_here"
    assert [b.seq for b in sc.history] == [1, 2, 3]
    assert b1.languages[0] == "ar"


def test_fan_out_renders_every_language_with_fallback():
    sc = SilentCall(TEXTS)
    sc.broadcast("W1", "please_sit", actor="sup", ts=1.0, languages_present={"id": 5, "ur": 2, "en": 1})
    fo = sc.fan_out("W1")
    assert fo["pictogram"] == "🪑" and fo["seq"] == 1
    assert fo["texts"]["id"] == "id-please_sit"
    assert fo["texts"]["ur"] == "en-please_sit"  # no Urdu text in this fixture → English fallback
    assert sc.active_for("W1", "ar")["text"] == "ar-please_sit"
    assert sc.fan_out("M1") is None


def test_clear_and_unknown_instruction():
    sc = SilentCall(TEXTS)
    sc.broadcast("W1", "please_sit", actor="sup", ts=1.0)
    sc.clear("W1", actor="sup", ts=2.0)
    assert sc.fan_out("W1") is None and len(sc.history) == 2
    with pytest.raises(SilentCallError):
        sc.broadcast("W1", "dance", actor="sup", ts=3.0)


def test_top_three_languages_always_include_arabic():
    langs = SilentCall.languages_for({"id": 9, "ur": 8, "bn": 7, "tr": 1})
    assert langs == ("ar", "id", "ur", "bn")
    assert SilentCall.languages_for(None) == ("ar",)
