"""Hawnan service — FastAPI JSON API and static pages.

Run: ``uvicorn app.main:app --port 8010``

Everything that decides something lives in ``hawnan_core``; this module only
persists events (SQLite, append-only), authenticates supervisors by device
token, applies security headers and a simple rate limit, and serves the pages.
No LLM, no external calls, no personal data.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import seed as seed_mod
from app.store import Store
from hawnan_core import __version__ as CORE_VERSION
from hawnan_core import twin as twin_mod
from hawnan_core.audit import AuditLog
from hawnan_core.batch_clock import NEXT_STATE, BatchClock, ClockError, InvalidTransition
from hawnan_core.content import ContentError, ContentLibrary
from hawnan_core.estimator import format_range, remaining_range
from hawnan_core.indicators import snapshot
from hawnan_core.journey import JourneyInput, fmt_hhmm
from hawnan_core.journey import render as render_journey
from hawnan_core.seal import PassPayload, Signer
from hawnan_core.silent_call import BY_ID, SilentCall

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "web"
CONTENT_DIR = ROOT / "content"
APP_VERSION = "0.1.0"
SESSION_COOKIE = "hawnan_device"
PAGES = {"": "index.html", "guest": "guest.html", "staff": "staff.html", "display": "display.html", "ops": "ops.html", "checkin": "checkin.html"}
SIM_BANNER = {"ar": "بيانات تصاريح محاكاة معلنة", "en": "Declared simulated permit data"}


@dataclass
class Config:
    db_path: str = field(default_factory=lambda: os.environ.get("HAWNAN_DB", str(ROOT / "hawnan.sqlite3")))
    content_key: str = field(default_factory=lambda: os.environ.get("HAWNAN_CONTENT_KEY", "hawnan-demo-content-key-2026-change-me"))
    audit_key: str = field(default_factory=lambda: os.environ.get("HAWNAN_AUDIT_KEY", "hawnan-demo-audit-key-2026-change-me"))
    permit_salt: str = field(default_factory=lambda: os.environ.get("HAWNAN_PERMIT_SALT", "hawnan-demo-permit-salt-2026"))
    staff_tokens: tuple[str, ...] = field(default_factory=lambda: tuple(t for t in os.environ.get("HAWNAN_STAFF_TOKENS", "demo-staff-1,demo-staff-2").split(",") if t))
    cookie_secure: bool = field(default_factory=lambda: os.environ.get("HAWNAN_COOKIE_SECURE", "0") == "1")
    rate_limit_per_min: int = field(default_factory=lambda: int(os.environ.get("HAWNAN_RATE_LIMIT", "120")))
    seed: int = field(default_factory=lambda: int(os.environ.get("HAWNAN_SEED", "2026")))


class Service:
    """Owns the clock, the signer, the content library, the audit chain and the store."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.lock = threading.RLock()
        self.store = Store(cfg.db_path)
        self.signer = Signer.from_env()
        self.content = ContentLibrary(cfg.content_key)
        self.refused_packs: list[dict] = []
        for path in sorted(CONTENT_DIR.glob("*.json")):
            try:
                self.content.load(json.loads(path.read_text(encoding="utf-8")))
            except (ContentError, ValueError) as exc:
                self.refused_packs.append({"file": path.name, "reason": str(exc)})
        self.audit = AuditLog.load(cfg.audit_key, self.store.load_audit())
        self.silent_call = SilentCall(self.content.instruction_texts())
        self.sim_permits: dict[str, seed_mod.SimPermit] = {}
        events = self.store.load_events()
        if events:
            self.clock = BatchClock.fold(events)
            seed_now = float(self.store.get_meta("seed_now") or time.time())
            self._load_sim_permits(seed_now)
        else:
            self.clock = BatchClock()
            self._seed(time.time())
        self._replay_instructions()

    # ---- seeding -----------------------------------------------------------
    def _seed(self, now: float) -> None:
        permits = seed_mod.build(self.clock, self.audit, now=now, seed=self.cfg.seed)
        self.store.append_events(self.clock.events)
        for rec in self.audit.records:
            self.store.append_audit(rec)
        self.store.add_permits(
            (self.hash_ref(p.ref), p.batch_id, p.point_id, p.lane, p.lang, p.hotel_area_en, p.distance_m, (now - 600.0) if p.checked_in else None, "simulated")
            for p in permits
        )
        self.store.set_meta("seed_now", repr(now))
        self.store.set_meta("feed", "simulated")
        self.sim_permits = {p.ref: p for p in permits}

    def _load_sim_permits(self, seed_now: float) -> None:
        scratch, scratch_audit = BatchClock(), AuditLog(self.cfg.audit_key)
        self.sim_permits = {p.ref: p for p in seed_mod.build(scratch, scratch_audit, now=seed_now, seed=self.cfg.seed)}

    def _replay_instructions(self) -> None:
        for ev in self.clock.events:
            if ev.type == "instruction_set":
                self.silent_call.broadcast(ev.point_id, ev.payload["instruction_id"], actor=ev.actor, ts=ev.ts, languages_present=self.languages_at(ev.point_id))
            elif ev.type == "instruction_cleared":
                self.silent_call.clear(ev.point_id, actor=ev.actor, ts=ev.ts)

    def reset(self, actor: str) -> None:
        with self.lock:
            self.store.wipe()
            self.clock = BatchClock()
            self.audit = AuditLog(self.cfg.audit_key)
            self.silent_call = SilentCall(self.content.instruction_texts())
            self._seed(time.time())
            self._replay_instructions()
            self._audit(actor, "reset", {})

    # ---- helpers -----------------------------------------------------------
    def hash_ref(self, ref: str) -> str:
        return hashlib.sha256((self.cfg.permit_salt + "|" + ref.strip().upper()).encode()).hexdigest()

    def _audit(self, actor: str, action: str, detail: dict) -> None:
        rec = self.audit.append(actor, action, detail, ts=time.time())
        self.store.append_audit(rec)

    def _apply(self, ev) -> None:
        self.store.append_event(ev)

    def lang_or_default(self, lang: str | None) -> str:
        return lang if lang and lang in self.content.packs else "ar"

    def languages_at(self, point_id: str) -> dict[str, int]:
        counts: dict[str, int] = defaultdict(int)
        for b in self.clock.point_batches(point_id):
            if b.state in ("checked_in", "holding", "prepare", "moving"):
                for lang, n in b.languages.items():
                    counts[lang] += n
        return dict(counts)

    def point_names(self, point_id: str, lang: str) -> dict:
        p = self.clock.points[point_id]
        rtl = self.content.pack(lang).dir == "rtl"
        defn = next((d for d in seed_mod.POINTS if d["id"] == point_id), None)
        gate_ar = defn["gate_ar"] if defn else p.gate
        return {"id": p.id, "lane": p.lane, "name": p.name_ar if rtl else p.name_en, "name_ar": p.name_ar, "name_en": p.name_en, "gate": gate_ar if rtl else p.gate, "gate_ar": gate_ar, "gate_en": p.gate, "capacity": p.capacity}

    def range_for(self, batch_id: str, lang: str, now: float) -> dict:
        r = remaining_range(self.clock, batch_id, now)
        ui = self.content.ui(lang)
        text = format_range(r, ui["about_minutes"]) if r.about else ""
        basis_text = ui.get(f"basis_{r.basis}", "")
        return {**r.to_dict(), "text": text, "basis_text": basis_text}

    def batch_view(self, batch_id: str, lang: str, now: float) -> dict:
        b = self.clock.batches[batch_id]
        ui = self.content.ui(lang)
        return {
            **b.to_dict(),
            "scheduled_hhmm": fmt_hhmm(b.scheduled_at),
            "protected_hhmm": fmt_hhmm(b.protected_until),
            "state_label": ui.get(f"state_{b.state}", b.state),
            "position": self.clock.position(batch_id) if b.state in ("issued", "checked_in", "holding", "prepare") else None,
            "range": self.range_for(batch_id, lang, now),
        }

    # ---- use cases ---------------------------------------------------------
    def checkin(self, permit_ref: str, lang_override: str | None, actor: str) -> dict:
        now = time.time()
        with self.lock:
            row = self.store.get_permit(self.hash_ref(permit_ref))
            if row is None:
                raise HTTPException(404, "permit not found in the (simulated) feed")
            batch = self.clock.batches[row["batch_id"]]
            lang = self.lang_or_default(lang_override or row["lang"])
            first_time = row["checked_in_at"] is None
            if first_time:
                if batch.state not in ("issued", "checked_in", "holding"):
                    raise HTTPException(409, f"batch {batch.id} is {batch.state}; check-in closed, please re-batch at the point")
                self._apply(self.clock.check_in_guest(batch.id, now, lang=lang, actor=actor))
                self.store.mark_checked_in(row["ref_hash"], now)
                self._audit(actor, "checkin", {"batch": batch.id, "point": batch.point_id, "lang": lang})
            payload = PassPayload(batch=batch.id, point=batch.point_id, lane=batch.lane, protected_until=int(batch.protected_until), issued_at=int(now))
            pass_text = self.signer.issue(payload)
            self._audit(actor, "pass_issued" if first_time else "pass_reissued", {"batch": batch.id, "point": batch.point_id})
            return {
                "pass": pass_text,
                "qr_payload": pass_text,
                "scheme": self.signer.scheme,
                "reissued": not first_time,
                "lang": lang,
                "batch": self.batch_view(batch.id, lang, now),
                "point": self.point_names(batch.point_id, lang),
                "guest_url": f"/guest?lang={lang}&permit={permit_ref.strip().upper()}&pass={pass_text}",
                "simulated": True,
            }

    def verify(self, pass_text: str, lang: str) -> dict:
        now = time.time()
        r = self.signer.verify(pass_text, now=now)
        out = r.to_dict()
        if r.payload and r.payload.batch in self.clock.batches:
            out["batch"] = self.batch_view(r.payload.batch, lang, now)
            out["point"] = self.point_names(r.payload.point, lang)
        elif r.valid:
            out["valid"], out["reason"] = False, "unknown_batch"
        out["verified_at"] = now
        out["simulated"] = True
        return out

    def point_state(self, point_id: str, lang: str) -> dict:
        now = time.time()
        if point_id not in self.clock.points:
            raise HTTPException(404, "unknown point")
        point = self.clock.points[point_id]
        langs = self.languages_at(point_id)
        top = self.silent_call.languages_for(langs)
        fan = self.silent_call.fan_out(point_id, tuple(dict.fromkeys((*top, lang))))
        queue = [self.batch_view(b.id, lang, now) for b in self.clock.queue(point_id) if b.state != "issued"][:6]
        moving = [self.batch_view(b.id, lang, now) for b in self.clock.point_batches(point_id) if b.state in ("moving", "inside")]
        upcoming = [self.batch_view(b.id, lang, now) for b in self.clock.queue(point_id) if b.state == "issued"][:3]
        return {
            "server_ts": now,
            "lang": lang,
            "dir": self.content.pack(lang).dir,
            "point": self.point_names(point_id, lang),
            "queue": queue,
            "moving": moving,
            "upcoming": upcoming,
            "active_instruction": self.silent_call.active_for(point_id, lang),
            "fan_out": fan,
            "instruction_seq": point.instruction_seq,
            "languages_present": langs,
            "top_languages": list(top),
            "simulated": True,
            "banner": SIM_BANNER,
        }

    def batch_state(self, batch_id: str, lang: str) -> dict:
        now = time.time()
        if batch_id not in self.clock.batches:
            raise HTTPException(404, "unknown batch")
        b = self.clock.batches[batch_id]
        view = self.batch_view(batch_id, lang, now)
        out = {
            "server_ts": now,
            "lang": lang,
            "dir": self.content.pack(lang).dir,
            "batch": view,
            "point": self.point_names(b.point_id, lang),
            "active_instruction": self.silent_call.active_for(b.point_id, lang),
            "instruction_seq": self.clock.points[b.point_id].instruction_seq,
            "simulated": True,
        }
        if b.state == "prepare":
            out["preparation"] = self.content.preparation(lang)
        return out

    def set_instruction(self, point_id: str, instruction_id: str | None, actor: str) -> dict:
        now = time.time()
        with self.lock:
            if point_id not in self.clock.points:
                raise HTTPException(404, "unknown point")
            if instruction_id is None:
                self._apply(self.clock.clear_instruction(point_id, now, actor))
                self.silent_call.clear(point_id, actor=actor, ts=now)
                self._audit(actor, "instruction_cleared", {"point": point_id})
                return {"point_id": point_id, "fan_out": None, "seq": self.clock.points[point_id].instruction_seq}
            if instruction_id not in BY_ID:
                raise HTTPException(400, "unknown instruction")
            self._apply(self.clock.set_instruction(point_id, instruction_id, now, actor))
            b = self.silent_call.broadcast(point_id, instruction_id, actor=actor, ts=now, languages_present=self.languages_at(point_id))
            self._audit(actor, "instruction_set", {"point": point_id, "instruction": instruction_id, "languages": list(b.languages)})
            return {"point_id": point_id, "fan_out": self.silent_call.fan_out(point_id), "seq": self.clock.points[point_id].instruction_seq}

    def advance(self, batch_id: str, actor: str, lang: str) -> dict:
        now = time.time()
        with self.lock:
            if batch_id not in self.clock.batches:
                raise HTTPException(404, "unknown batch")
            b = self.clock.batches[batch_id]
            if b.state == "issued":
                raise HTTPException(409, "batch has no checked-in guests yet")
            try:
                ev = self.clock.advance(batch_id, now, actor)
            except InvalidTransition as exc:
                raise HTTPException(409, str(exc)) from exc
            self._apply(ev)
            for stage, seconds in b.stage_durations().items():
                if not any(m.batch_id == b.id and m.stage == stage for m in self.clock.measurements):
                    self._apply(self.clock.record_measurement(b.point_id, b.id, stage, round(seconds, 1), now, "live-demo"))
            self._audit(actor, "advance", {"batch": b.id, "to": b.state})
            return {"batch": self.batch_view(b.id, lang, now), "next": NEXT_STATE[b.state]}

    def journey(self, permit_ref: str, lang: str | None) -> dict:
        row = self.store.get_permit(self.hash_ref(permit_ref))
        if row is None:
            raise HTTPException(404, "permit not found in the (simulated) feed")
        lang = self.lang_or_default(lang or row["lang"])
        b = self.clock.batches[row["batch_id"]]
        names = self.point_names(b.point_id, lang)
        sim = self.sim_permits.get(permit_ref.strip().upper())
        hotel_area = (sim.hotel_area_ar if self.content.pack(lang).dir == "rtl" else sim.hotel_area_en) if sim else row["hotel_area"]
        inp = JourneyInput(b.number, b.scheduled_at, names["gate"], names["name"], hotel_area, float(row["distance_m"]))
        msgs = render_journey(self.content.journey_templates(lang), inp)
        return {
            "lang": lang,
            "dir": self.content.pack(lang).dir,
            "batch": {"id": b.id, "number": b.number, "point_id": b.point_id, "lane": b.lane, "scheduled_hhmm": msgs["slot"], "protected_hhmm": fmt_hhmm(b.protected_until)},
            "point": names,
            "hotel_area": hotel_area,
            "distance_m": row["distance_m"],
            "messages": {k: msgs[k] for k in ("t24", "t90", "t30", "protected_note")},
            "slot": msgs["slot"],
            "depart": msgs["depart"],
            "walk_min": msgs["walk_min"],
            "simulated": True,
        }

    def showme(self, lang: str, batch_id: str | None) -> list[dict]:
        ui = self.content.ui(lang)
        ui_ar = self.content.ui("ar")
        lane, lane_ar, hhmm = "…", "…", "…"
        if batch_id and batch_id in self.clock.batches:
            b = self.clock.batches[batch_id]
            lane, lane_ar, hhmm = ui[f"lane_{b.lane}"], ui_ar[f"lane_{b.lane}"], fmt_hhmm(b.scheduled_at)
        cards = []
        for c in self.content.showme(lang):
            cards.append({"id": c["id"], "text": c["text"].replace("{lane}", lane).replace("{time}", hhmm), "ar": c["ar"].replace("{lane}", lane_ar).replace("{time}", hhmm)})
        return cards

    def sample_permits(self, point_id: str | None, n: int) -> list[dict]:
        out = []
        for p in self.sim_permits.values():
            if point_id and p.point_id != point_id:
                continue
            row = self.store.get_permit(self.hash_ref(p.ref))
            if row is None or row["checked_in_at"] is not None:
                continue
            b = self.clock.batches[p.batch_id]
            if b.state not in ("issued", "checked_in", "holding"):
                continue
            out.append({"ref": p.ref, "point_id": p.point_id, "lane": p.lane, "lang": p.lang, "batch_id": b.id, "batch_number": b.number, "scheduled_hhmm": fmt_hhmm(b.scheduled_at), "demo": not p.ref[4:].isdigit() and "-" in p.ref[4:]})
        out.sort(key=lambda r: (not r["demo"], r["batch_number"]))
        return out[:n]

    def runtime(self) -> dict:
        return {
            "app": "hawnan",
            "name_ar": "هَوْنًا إلى الروضة",
            "version": APP_VERSION,
            "core_version": CORE_VERSION,
            "server_time": time.time(),
            "seal": self.signer.describe(),
            "content": {"packs": len(self.content.packs), "review": self.content.review_status(), "refused": self.refused_packs, "signature_scheme": "hmac-sha256 (team key; Authority key in production)"},
            "permit_feed": {"source": "simulated", "declared": True, "banner": SIM_BANNER, "permits": self.store.permit_stats()},
            "simulated_permit_feed": True,
            "llm_at_runtime": False,
            "storage": "sqlite (append-only events, HMAC-chained audit)",
            "audit": self.audit.verify().to_dict(),
            "events": self.store.count_events(),
        }


# ---- HTTP layer ----------------------------------------------------------------
class CheckinIn(BaseModel):
    permit_ref: str = Field(min_length=3, max_length=40)
    lang: str | None = Field(default=None, max_length=5)


class VerifyIn(BaseModel):
    pass_text: str = Field(alias="pass", min_length=5, max_length=1024)
    lang: str | None = Field(default=None, max_length=5)

    model_config = {"populate_by_name": True}


class InstructionIn(BaseModel):
    point_id: str = Field(max_length=16)
    instruction_id: str | None = Field(default=None, max_length=40)


class AdvanceIn(BaseModel):
    batch_id: str = Field(max_length=32)
    lang: str | None = Field(default=None, max_length=5)


def create_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or Config()
    svc = Service(cfg)
    app = FastAPI(title="Hawnan — هَوْنًا إلى الروضة", version=APP_VERSION, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.service = svc
    hits: dict[str, deque] = defaultdict(deque)
    hits_lock = threading.Lock()

    def actor_of(request: Request) -> str:
        return "device:" + hashlib.sha256(request.state.device.encode()).hexdigest()[:10]

    def staff_actor(request: Request) -> str:
        token = request.headers.get("x-device-token", "")
        for i, t in enumerate(cfg.staff_tokens, start=1):
            if hmac.compare_digest(token.encode(), t.encode()):
                return f"staff:{i}"
        raise HTTPException(401, "supervisor device token required")

    def lang_q(lang: str | None) -> str:
        return svc.lang_or_default(lang)

    @app.middleware("http")
    async def session_and_security(request: Request, call_next):
        device = request.cookies.get(SESSION_COOKIE, "")
        is_new = not (len(device) == 32 and device.isalnum())
        if is_new:
            device = secrets.token_hex(16)
        request.state.device = device
        if request.method == "POST" and request.url.path.startswith("/api/"):
            key = (request.client.host if request.client else "?") + "|" + device
            now = time.time()
            with hits_lock:
                q = hits[key]
                while q and q[0] < now - 60:
                    q.popleft()
                if len(q) >= cfg.rate_limit_per_min:
                    return JSONResponse({"detail": "rate limit"}, status_code=429)
                q.append(now)
        response = await call_next(request)
        if is_new:
            response.set_cookie(SESSION_COOKIE, device, max_age=31_536_000, httponly=True, secure=cfg.cookie_secure, samesite="lax")
        h = response.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        h.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        h.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; base-uri 'none'; object-src 'none'; frame-ancestors 'none'; form-action 'self'; "
            "img-src 'self' data:; connect-src 'self'; manifest-src 'self'; worker-src 'self'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' data: https://fonts.gstatic.com",
        )
        if request.url.path.startswith("/api/"):
            h.setdefault("Cache-Control", "no-store")
        if request.url.path == "/sw.js":
            h.setdefault("Service-Worker-Allowed", "/")
        return response

    # ---- API
    @app.get("/api/runtime")
    def runtime():
        return svc.runtime()

    @app.get("/api/points")
    def points(lang: str | None = None):
        lang = lang_q(lang)
        now = time.time()
        out = []
        for pid in svc.clock.points:
            q = [b for b in svc.clock.queue(pid) if b.state != "issued"]
            out.append({**svc.point_names(pid, lang), "waiting_batches": len(q), "waiting_guests": sum(b.guests for b in q), "active_instruction": svc.silent_call.active_for(pid, lang), "next": svc.batch_view(q[0].id, lang, now) if q else None})
        return {"points": out, "simulated": True, "banner": SIM_BANNER}

    @app.get("/api/permits/sample")
    def permits_sample(point_id: str | None = None, n: int = Query(default=8, ge=1, le=40)):
        return {"source": "simulated", "declared": True, "permits": svc.sample_permits(point_id, n)}

    @app.post("/api/checkin")
    def checkin(body: CheckinIn, request: Request):
        return svc.checkin(body.permit_ref, body.lang, actor_of(request))

    @app.post("/api/verify")
    def verify(body: VerifyIn):
        return svc.verify(body.pass_text, lang_q(body.lang))

    @app.get("/api/point/{point_id}/state")
    def point_state(point_id: str, lang: str | None = None):
        return svc.point_state(point_id, lang_q(lang))

    @app.get("/api/batch/{batch_id}")
    def batch(batch_id: str, lang: str | None = None):
        return svc.batch_state(batch_id, lang_q(lang))

    @app.get("/api/point/{point_id}/batches")
    def point_batches(point_id: str, lang: str | None = None):
        if point_id not in svc.clock.points:
            raise HTTPException(404, "unknown point")
        now = time.time()
        return {"point": svc.point_names(point_id, lang_q(lang)), "batches": [svc.batch_view(b.id, lang_q(lang), now) for b in svc.clock.point_batches(point_id)], "simulated": True}

    @app.post("/api/supervisor/instruction")
    def supervisor_instruction(body: InstructionIn, request: Request):
        return svc.set_instruction(body.point_id, body.instruction_id, staff_actor(request))

    @app.post("/api/supervisor/advance")
    def supervisor_advance(body: AdvanceIn, request: Request):
        return svc.advance(body.batch_id, staff_actor(request), lang_q(body.lang))

    @app.post("/api/supervisor/reset")
    def supervisor_reset(request: Request):
        svc.reset(staff_actor(request))
        return {"ok": True, "events": svc.store.count_events()}

    @app.get("/api/journey/{permit_ref}")
    def journey(permit_ref: str, lang: str | None = None):
        return svc.journey(permit_ref, lang)

    @app.get("/api/showme")
    def showme(lang: str | None = None, batch_id: str | None = None):
        lang = lang_q(lang)
        return {"lang": lang, "dir": svc.content.pack(lang).dir, "cards": svc.showme(lang, batch_id)}

    @app.get("/api/content/{kind}")
    def content(kind: str, lang: str | None = None):
        lang = lang_q(lang)
        pack = svc.content.pack(lang)
        if kind == "languages":
            return {"languages": svc.content.languages()}
        if kind == "ui":
            return {"lang": pack.lang, "dir": pack.dir, "ui": svc.content.ui(lang), "banner": SIM_BANNER}
        if kind == "preparation":
            return {"lang": pack.lang, "dir": pack.dir, "preparation": svc.content.preparation(lang)}
        if kind == "instructions":
            return {"lang": pack.lang, "dir": pack.dir, "instructions": svc.silent_call.catalogue(lang), "ar": {i["id"]: i["text"] for i in svc.silent_call.catalogue("ar")}}
        if kind == "journey":
            return {"lang": pack.lang, "templates": svc.content.journey_templates(lang)}
        if kind == "showme":
            return {"lang": pack.lang, "dir": pack.dir, "cards": svc.showme(lang, None)}
        if kind == "review":
            return {"packs": svc.content.review_status(), "refused": svc.refused_packs}
        raise HTTPException(404, "unknown content kind")

    @app.get("/api/indicators")
    def indicators():
        now = time.time()
        return {**snapshot(svc.clock, now), "content_review": svc.content.review_status(), "audit": svc.audit.verify().to_dict(), "simulated": True, "banner": SIM_BANNER}

    @app.post("/api/twin/run")
    def twin_run(body: dict[str, Any] = Body(default_factory=dict)):
        compare = bool(body.pop("compare", False))
        try:
            params = twin_mod.TwinParams.from_dict(body)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc)) from exc
        if params.permits_per_day > 100_000:
            raise HTTPException(422, "permits_per_day is capped at 100000 in the prototype")
        t0 = time.perf_counter()
        if compare:
            result: dict = {"results": twin_mod.compare(params)}
        else:
            result = {"result": twin_mod.run(params).to_dict()}
        result.update({"engine": "hawnan_core.twin", "same_batch_clock": True, "runtime_s": round(time.perf_counter() - t0, 2), "simulated": True})
        return result

    @app.get("/api/audit/verify")
    def audit_verify():
        check = svc.audit.verify()
        return {**check.to_dict(), "head": svc.audit.head, "scheme": "hmac-sha256 chain"}

    @app.get("/api/audit/recent")
    def audit_recent(n: int = Query(default=20, ge=1, le=200)):
        return {"records": [r.to_dict() for r in svc.audit.records[-n:]][::-1], "ok": svc.audit.verify().ok}

    # ---- pages and static files
    for route, filename in PAGES.items():
        def _page(filename=filename):
            return FileResponse(WEB_DIR / filename, media_type="text/html; charset=utf-8")

        app.add_api_route("/" + route, _page, methods=["GET"], include_in_schema=False)

    @app.get("/sw.js", include_in_schema=False)
    def sw():
        return FileResponse(WEB_DIR / "static" / "sw.js", media_type="application/javascript")

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(WEB_DIR / "static" / "manifest.webmanifest", media_type="application/manifest+json")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")
    return app


app = create_app()
