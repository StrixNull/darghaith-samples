"""HMAC-chained append-only audit log.

Each record's hash covers the previous hash and the canonical record body, so
removing, reordering or editing any record breaks every later hash. The key
never leaves the server; verification recomputes the chain.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from typing import Iterable

GENESIS = "0" * 64


@dataclass(frozen=True)
class AuditRecord:
    seq: int
    ts: float
    actor: str
    action: str
    detail: dict
    prev_hash: str
    hash: str

    def body(self) -> bytes:
        return json.dumps(
            {"seq": self.seq, "ts": self.ts, "actor": self.actor, "action": self.action, "detail": self.detail},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode()

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "actor": self.actor,
            "action": self.action,
            "detail": dict(self.detail),
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


@dataclass(frozen=True)
class ChainCheck:
    ok: bool
    length: int
    first_bad_seq: int | None = None

    def to_dict(self) -> dict:
        return {"ok": self.ok, "length": self.length, "first_bad_seq": self.first_bad_seq}


def compute_hash(key: bytes, prev_hash: str, body: bytes) -> str:
    return hmac.new(key, prev_hash.encode() + b"|" + body, hashlib.sha256).hexdigest()


@dataclass
class AuditLog:
    key: bytes
    records: list[AuditRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if isinstance(self.key, str):
            self.key = self.key.encode()
        if len(self.key) < 16:
            raise ValueError("audit key too short")

    @property
    def head(self) -> str:
        return self.records[-1].hash if self.records else GENESIS

    def append(self, actor: str, action: str, detail: dict | None, ts: float) -> AuditRecord:
        seq = len(self.records) + 1
        prev = self.head
        draft = AuditRecord(seq, float(ts), actor, action, dict(detail or {}), prev, "")
        rec = AuditRecord(seq, float(ts), actor, action, dict(detail or {}), prev, compute_hash(self.key, prev, draft.body()))
        self.records.append(rec)
        return rec

    @classmethod
    def load(cls, key: bytes | str, records: Iterable[dict]) -> "AuditLog":
        log = cls(key)  # type: ignore[arg-type]
        for d in records:
            log.records.append(
                AuditRecord(int(d["seq"]), float(d["ts"]), str(d["actor"]), str(d["action"]), dict(d.get("detail") or {}), str(d["prev_hash"]), str(d["hash"]))
            )
        return log

    def verify(self) -> ChainCheck:
        prev = GENESIS
        for i, rec in enumerate(self.records, start=1):
            if rec.seq != i or rec.prev_hash != prev:
                return ChainCheck(False, len(self.records), rec.seq)
            expected = compute_hash(self.key, prev, rec.body())
            if not hmac.compare_digest(expected, rec.hash):
                return ChainCheck(False, len(self.records), rec.seq)
            prev = rec.hash
        return ChainCheck(True, len(self.records))
