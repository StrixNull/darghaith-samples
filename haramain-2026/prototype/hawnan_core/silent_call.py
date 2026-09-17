"""Silent Call — the supervisor's catalogue of canonical instructions.

Twenty stable instruction ids, each with a pictogram and text in ten
languages (texts come from the signed content packs). Exactly one instruction
is active per holding point; every broadcast is kept in the history so the
audit chain and the displays can replay it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

LANGS: tuple[str, ...] = ("ar", "en", "ur", "id", "tr", "bn", "fr", "ms", "ha", "fa")
FALLBACK_ORDER: tuple[str, ...] = ("en", "ar")


@dataclass(frozen=True)
class Instruction:
    id: str
    pictogram: str  # emoji or symbol rendered large
    icon_name: str  # stable name for a future SVG set
    group: str  # "wait" | "move" | "conduct" | "info"
    forbidden: bool = False  # render with a "no" ring (e.g. no photography)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "pictogram": self.pictogram,
            "icon_name": self.icon_name,
            "group": self.group,
            "forbidden": self.forbidden,
        }


CATALOGUE: tuple[Instruction, ...] = (
    Instruction("wait_here", "✋", "hand-stop", "wait"),
    Instruction("please_sit", "🪑", "chair", "wait"),
    Instruction("please_stand", "🧍", "person-standing", "move"),
    Instruction("advance_calmly", "🚶", "person-walking", "move"),
    Instruction("keep_moving", "➡️", "arrow-right", "move"),
    Instruction("form_lines", "☰", "lines", "move"),
    Instruction("stay_with_group", "👥", "group", "conduct"),
    Instruction("next_batch_5", "⏱", "timer", "info"),
    Instruction("slight_delay", "⏳", "hourglass", "info"),
    Instruction("keep_pass_ready", "🎫", "ticket", "conduct"),
    Instruction("silence_please", "🤫", "quiet", "conduct"),
    Instruction("phones_away", "📵", "phone-off", "conduct"),
    Instruction("no_photography", "📷", "camera", "conduct", forbidden=True),
    Instruction("follow_staff", "🪧", "sign", "move"),
    Instruction("elderly_priority", "🧓", "elder", "conduct"),
    Instruction("prepare_now", "🕙", "clock-ten", "info"),
    Instruction("entry_started", "🟢", "green-circle", "info"),
    Instruction("time_inside_limited", "⌛", "hourglass-done", "info"),
    Instruction("exit_this_way", "🚪", "door", "move"),
    Instruction("batch_complete", "✅", "check", "info"),
)
BY_ID: dict[str, Instruction] = {i.id: i for i in CATALOGUE}


class SilentCallError(ValueError):
    pass


@dataclass(frozen=True)
class Broadcast:
    seq: int
    point_id: str
    instruction_id: str | None  # None = cleared
    actor: str
    ts: float
    languages: tuple[str, ...]  # languages present at the point when sent

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "point_id": self.point_id,
            "instruction_id": self.instruction_id,
            "actor": self.actor,
            "ts": self.ts,
            "languages": list(self.languages),
        }


@dataclass
class SilentCall:
    """Single-active-instruction state per point plus fan-out rendering.

    ``texts`` maps lang → instruction id → text, and comes from the content
    library so that only signed, reviewed-or-flagged text can be broadcast.
    """

    texts: dict[str, dict[str, str]]
    active: dict[str, Broadcast] = field(default_factory=dict)
    history: list[Broadcast] = field(default_factory=list)

    def broadcast(
        self,
        point_id: str,
        instruction_id: str,
        *,
        actor: str,
        ts: float,
        languages_present: dict[str, int] | None = None,
    ) -> Broadcast:
        if instruction_id not in BY_ID:
            raise SilentCallError(f"unknown instruction: {instruction_id}")
        langs = self.languages_for(languages_present)
        b = Broadcast(len(self.history) + 1, point_id, instruction_id, actor, ts, langs)
        self.active[point_id] = b  # replaces whatever was active: one per point
        self.history.append(b)
        return b

    def clear(self, point_id: str, *, actor: str, ts: float) -> Broadcast:
        b = Broadcast(len(self.history) + 1, point_id, None, actor, ts, ())
        self.active.pop(point_id, None)
        self.history.append(b)
        return b

    @staticmethod
    def languages_for(languages_present: dict[str, int] | None, top: int = 3) -> tuple[str, ...]:
        """Most common languages at the point, Arabic always included first."""
        counts = dict(languages_present or {})
        ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        langs = [lang for lang, _ in ordered if lang in LANGS][:top]
        if "ar" not in langs:
            langs.insert(0, "ar")
        return tuple(langs)

    def text(self, instruction_id: str, lang: str) -> str:
        for candidate in (lang, *FALLBACK_ORDER):
            t = self.texts.get(candidate, {}).get(instruction_id)
            if t:
                return t
        raise SilentCallError(f"no text for {instruction_id}")

    def render(self, instruction_id: str, lang: str) -> dict:
        ins = BY_ID[instruction_id]
        return {**ins.to_dict(), "lang": lang, "text": self.text(instruction_id, lang)}

    def fan_out(self, point_id: str, langs: tuple[str, ...] | list[str] | None = None) -> dict | None:
        """What every phone and display at the point should show right now."""
        b = self.active.get(point_id)
        if b is None or b.instruction_id is None:
            return None
        langs = tuple(langs) if langs else b.languages
        ins = BY_ID[b.instruction_id]
        return {
            "seq": b.seq,
            "point_id": point_id,
            "set_at": b.ts,
            "actor": b.actor,
            **ins.to_dict(),
            "texts": {lang: self.text(b.instruction_id, lang) for lang in langs},
        }

    def active_for(self, point_id: str, lang: str) -> dict | None:
        b = self.active.get(point_id)
        if b is None or b.instruction_id is None:
            return None
        return {"seq": b.seq, "set_at": b.ts, **self.render(b.instruction_id, lang)}

    def catalogue(self, lang: str) -> list[dict]:
        return [self.render(i.id, lang) for i in CATALOGUE]
