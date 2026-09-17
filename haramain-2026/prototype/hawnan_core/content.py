"""Signed content packs.

A pack is one JSON document per language with the instruction texts, the
Show-Me cards, the preparation card, the journey templates and the UI labels.
The Authority signs the body (everything except ``signature``) with its key;
this prototype uses a team key and marks every non-native draft
``"reviewed": false``. Unsigned or tampered packs are refused, never shown.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field

LANG_NAMES: dict[str, tuple[str, str]] = {  # code → (native name, direction)
    "ar": ("العربية", "rtl"),
    "en": ("English", "ltr"),
    "ur": ("اردو", "rtl"),
    "id": ("Bahasa Indonesia", "ltr"),
    "tr": ("Türkçe", "ltr"),
    "bn": ("বাংলা", "ltr"),
    "fr": ("Français", "ltr"),
    "ms": ("Bahasa Melayu", "ltr"),
    "ha": ("Hausa", "ltr"),
    "fa": ("فارسی", "rtl"),
}
REQUIRED_SECTIONS: tuple[str, ...] = ("instructions", "showme", "preparation", "journey", "ui")
SHOWME_IDS: tuple[str, ...] = (
    "elderly_sit",
    "this_place_batch",
    "lost_group",
    "female_staff",
    "where_exit",
    "unwell",
    "phone_dead",
    "need_water",
)
SIGNATURE_SCHEME = "hmac-sha256"


class ContentError(ValueError):
    pass


class UnsignedPack(ContentError):
    pass


class TamperedPack(ContentError):
    pass


def canonical(body: dict) -> bytes:
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def pack_digest(body: dict) -> str:
    return hashlib.sha256(canonical(body)).hexdigest()


def _body(pack: dict) -> dict:
    return {k: v for k, v in pack.items() if k != "signature"}


def sign_pack(pack: dict, key: bytes | str, key_id: str = "team-2026") -> dict:
    key = key.encode() if isinstance(key, str) else key
    body = _body(pack)
    mac = hmac.new(key, canonical(body), hashlib.sha256).hexdigest()
    return {**body, "signature": {"scheme": SIGNATURE_SCHEME, "key_id": key_id, "value": mac}}


def verify_pack(pack: dict, key: bytes | str) -> str:
    """Return the body digest if the signature is valid; raise otherwise."""
    key = key.encode() if isinstance(key, str) else key
    sig = pack.get("signature")
    if not isinstance(sig, dict) or not sig.get("value"):
        raise UnsignedPack("content pack has no signature")
    if sig.get("scheme") != SIGNATURE_SCHEME:
        raise UnsignedPack(f"unsupported signature scheme {sig.get('scheme')!r}")
    body = _body(pack)
    expected = hmac.new(key, canonical(body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(sig["value"])):
        raise TamperedPack("content pack signature does not match its body")
    return pack_digest(body)


@dataclass
class Pack:
    lang: str
    name: str
    dir: str
    reviewed: bool
    version: str
    digest: str
    key_id: str
    body: dict = field(repr=False)

    def section(self, name: str) -> dict | list:
        return self.body[name]

    def status(self) -> dict:
        return {
            "lang": self.lang,
            "name": self.name,
            "dir": self.dir,
            "reviewed": self.reviewed,
            "version": self.version,
            "digest": self.digest[:16],
            "key_id": self.key_id,
            "instructions": len(self.body["instructions"]),
            "showme": len(self.body["showme"]),
        }


class ContentLibrary:
    """Holds verified packs. ``load`` refuses anything unsigned or tampered."""

    def __init__(self, key: bytes | str):
        self.key = key.encode() if isinstance(key, str) else key
        if len(self.key) < 16:
            raise ContentError("content key too short")
        self.packs: dict[str, Pack] = {}

    def load(self, pack: dict) -> Pack:
        digest = verify_pack(pack, self.key)
        lang = str(pack.get("lang", ""))
        if lang not in LANG_NAMES:
            raise ContentError(f"unknown language {lang!r}")
        for section in REQUIRED_SECTIONS:
            if section not in pack:
                raise ContentError(f"pack {lang} is missing section {section!r}")
        showme_ids = [c.get("id") for c in pack["showme"]]
        if showme_ids != list(SHOWME_IDS):
            raise ContentError(f"pack {lang}: Show-Me cards must be exactly {SHOWME_IDS}")
        if not isinstance(pack.get("reviewed"), bool):
            raise ContentError(f"pack {lang}: 'reviewed' must be a boolean")
        native, direction = LANG_NAMES[lang]
        p = Pack(
            lang=lang,
            name=str(pack.get("name") or native),
            dir=str(pack.get("dir") or direction),
            reviewed=bool(pack["reviewed"]),
            version=str(pack.get("version", "")),
            digest=digest,
            key_id=str(pack["signature"].get("key_id", "")),
            body=_body(pack),
        )
        self.packs[lang] = p
        return p

    # ---- queries -------------------------------------------------------
    def languages(self) -> list[dict]:
        return [
            {"code": p.lang, "name": p.name, "dir": p.dir, "reviewed": p.reviewed}
            for p in sorted(self.packs.values(), key=lambda p: list(LANG_NAMES).index(p.lang))
        ]

    def pack(self, lang: str) -> Pack:
        if lang in self.packs:
            return self.packs[lang]
        for fb in ("en", "ar"):
            if fb in self.packs:
                return self.packs[fb]
        raise ContentError("no content packs loaded")

    def instruction_texts(self) -> dict[str, dict[str, str]]:
        return {lang: dict(p.body["instructions"]) for lang, p in self.packs.items()}

    def ui(self, lang: str) -> dict:
        base = dict(self.packs["en"].body["ui"]) if "en" in self.packs else {}
        base.update(self.pack(lang).body["ui"])
        return base

    def showme(self, lang: str) -> list[dict]:
        """Cards in the guest's language with the Arabic side attached."""
        ar = {c["id"]: c["text"] for c in self.packs["ar"].body["showme"]} if "ar" in self.packs else {}
        return [
            {"id": c["id"], "text": c["text"], "ar": ar.get(c["id"], c["text"])}
            for c in self.pack(lang).body["showme"]
        ]

    def preparation(self, lang: str) -> dict:
        return dict(self.pack(lang).body["preparation"])

    def journey_templates(self, lang: str) -> dict:
        return dict(self.pack(lang).body["journey"])

    def review_status(self) -> list[dict]:
        return [p.status() for p in self.packs.values()]


def _cli() -> None:  # pragma: no cover - thin wrapper around sign_pack/verify_pack
    """Sign or verify the JSON packs in a directory: python -m hawnan_core.content sign content/"""
    import os
    import sys

    if len(sys.argv) != 3 or sys.argv[1] not in ("sign", "verify"):
        print("usage: python -m hawnan_core.content sign|verify <dir>")
        raise SystemExit(2)
    key = os.environ.get("HAWNAN_CONTENT_KEY", "hawnan-demo-content-key-2026-change-me")
    key_id = os.environ.get("HAWNAN_CONTENT_KEY_ID", "team-2026")
    folder = sys.argv[2]
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        with open(path, encoding="utf-8") as fh:
            pack = json.load(fh)
        if sys.argv[1] == "sign":
            signed = sign_pack(pack, key, key_id)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(signed, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            print(f"signed  {name}  {pack_digest(_body(signed))[:16]}")
        else:
            try:
                print(f"ok      {name}  {verify_pack(pack, key)[:16]}  reviewed={pack.get('reviewed')}")
            except ContentError as exc:
                print(f"REFUSED {name}  {exc}")
                raise SystemExit(1)


if __name__ == "__main__":
    _cli()
