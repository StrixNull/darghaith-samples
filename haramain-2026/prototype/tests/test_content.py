import copy
import json
from pathlib import Path

import pytest

from hawnan_core.content import ContentLibrary, TamperedPack, UnsignedPack, sign_pack, verify_pack

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"
KEY = "hawnan-demo-content-key-2026-change-me"


def load_all():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(CONTENT_DIR.glob("*.json"))}


def test_all_ten_packs_load_and_verify():
    lib = ContentLibrary(KEY)
    for pack in load_all().values():
        lib.load(pack)
    assert sorted(lib.packs) == ["ar", "bn", "en", "fa", "fr", "ha", "id", "ms", "tr", "ur"]
    assert lib.packs["ar"].reviewed and lib.packs["en"].reviewed
    assert all(not lib.packs[l].reviewed for l in ("ur", "id", "tr", "bn", "fr", "ms", "ha", "fa"))
    assert [l["name"] for l in lib.languages()][:3] == ["العربية", "English", "اردو"]


def test_unsigned_pack_is_refused():
    lib = ContentLibrary(KEY)
    pack = load_all()["en"]
    naked = {k: v for k, v in pack.items() if k != "signature"}
    with pytest.raises(UnsignedPack):
        lib.load(naked)
    assert "en" not in lib.packs


def test_tampered_pack_is_refused_even_for_the_reviewed_flag():
    lib = ContentLibrary(KEY)
    pack = copy.deepcopy(load_all()["id"])
    pack["reviewed"] = True  # flipping the review flag must break the signature
    with pytest.raises(TamperedPack):
        lib.load(pack)
    pack2 = copy.deepcopy(load_all()["id"])
    pack2["instructions"]["please_sit"] = "changed"
    with pytest.raises(TamperedPack):
        verify_pack(pack2, KEY)


def test_wrong_key_is_refused_and_resigning_works():
    pack = load_all()["en"]
    with pytest.raises(TamperedPack):
        verify_pack(pack, "some-other-key-of-enough-length")
    resigned = sign_pack(pack, "some-other-key-of-enough-length", "other")
    assert verify_pack(resigned, "some-other-key-of-enough-length")


def test_showme_cards_carry_arabic_side_and_no_eastern_digits():
    lib = ContentLibrary(KEY)
    for pack in load_all().values():
        lib.load(pack)
    cards = lib.showme("id")
    assert [c["id"] for c in cards][0] == "elderly_sit"
    assert cards[0]["ar"] == "أنا من كبار السن، هل يمكنني الجلوس؟"
    blob = json.dumps([p.body for p in lib.packs.values()], ensure_ascii=False)
    assert not any("٠" <= ch <= "٩" or "۰" <= ch <= "۹" for ch in blob)
