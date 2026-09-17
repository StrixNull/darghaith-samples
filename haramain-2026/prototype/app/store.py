"""SQLite persistence: append-only events, the audit chain and hashed permits.

Nothing personal is stored: a permit is known only by a salted hash of its
reference, its batch, its language and a coarse hotel area.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Iterable

from hawnan_core.audit import AuditRecord
from hawnan_core.batch_clock import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL, type TEXT NOT NULL, batch_id TEXT NOT NULL, point_id TEXT NOT NULL,
  payload_json TEXT NOT NULL, actor TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
  seq INTEGER PRIMARY KEY, ts REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL,
  detail_json TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS permits (
  ref_hash TEXT PRIMARY KEY, batch_id TEXT NOT NULL, point_id TEXT NOT NULL, lane TEXT NOT NULL,
  lang TEXT NOT NULL, hotel_area TEXT NOT NULL, distance_m REAL NOT NULL,
  checked_in_at REAL, source TEXT NOT NULL DEFAULT 'simulated'
);
CREATE INDEX IF NOT EXISTS permits_batch ON permits(batch_id);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            if path != ":memory:":
                self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # ---- events ----------------------------------------------------------
    def append_event(self, ev: Event) -> int:
        with self.lock:
            cur = self.conn.execute(
                "INSERT INTO events(ts,type,batch_id,point_id,payload_json,actor) VALUES (?,?,?,?,?,?)",
                (ev.ts, ev.type, ev.batch_id, ev.point_id, json.dumps(ev.payload, ensure_ascii=False), ev.actor),
            )
            self.conn.commit()
            return int(cur.lastrowid)

    def append_events(self, events: Iterable[Event]) -> None:
        with self.lock:
            self.conn.executemany(
                "INSERT INTO events(ts,type,batch_id,point_id,payload_json,actor) VALUES (?,?,?,?,?,?)",
                [(e.ts, e.type, e.batch_id, e.point_id, json.dumps(e.payload, ensure_ascii=False), e.actor) for e in events],
            )
            self.conn.commit()

    def load_events(self) -> list[Event]:
        with self.lock:
            rows = self.conn.execute("SELECT ts,type,batch_id,point_id,payload_json,actor FROM events ORDER BY id").fetchall()
        return [Event(r["ts"], r["type"], r["batch_id"], r["point_id"], json.loads(r["payload_json"]), r["actor"]) for r in rows]

    def count_events(self) -> int:
        with self.lock:
            return int(self.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0])

    # ---- audit -----------------------------------------------------------
    def append_audit(self, rec: AuditRecord) -> None:
        with self.lock:
            self.conn.execute(
                "INSERT INTO audit(seq,ts,actor,action,detail_json,prev_hash,hash) VALUES (?,?,?,?,?,?,?)",
                (rec.seq, rec.ts, rec.actor, rec.action, json.dumps(rec.detail, ensure_ascii=False), rec.prev_hash, rec.hash),
            )
            self.conn.commit()

    def load_audit(self) -> list[dict]:
        with self.lock:
            rows = self.conn.execute("SELECT seq,ts,actor,action,detail_json,prev_hash,hash FROM audit ORDER BY seq").fetchall()
        return [
            {"seq": r["seq"], "ts": r["ts"], "actor": r["actor"], "action": r["action"], "detail": json.loads(r["detail_json"]), "prev_hash": r["prev_hash"], "hash": r["hash"]}
            for r in rows
        ]

    # ---- permits (hashed) ----------------------------------------------
    def add_permits(self, rows: Iterable[tuple]) -> None:
        with self.lock:
            self.conn.executemany(
                "INSERT OR IGNORE INTO permits(ref_hash,batch_id,point_id,lane,lang,hotel_area,distance_m,checked_in_at,source) VALUES (?,?,?,?,?,?,?,?,?)",
                list(rows),
            )
            self.conn.commit()

    def get_permit(self, ref_hash: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM permits WHERE ref_hash=?", (ref_hash,)).fetchone()
        return dict(r) if r else None

    def mark_checked_in(self, ref_hash: str, ts: float) -> None:
        with self.lock:
            self.conn.execute("UPDATE permits SET checked_in_at=? WHERE ref_hash=?", (ts, ref_hash))
            self.conn.commit()

    def permit_stats(self) -> dict:
        with self.lock:
            total = self.conn.execute("SELECT COUNT(*) FROM permits").fetchone()[0]
            checked = self.conn.execute("SELECT COUNT(*) FROM permits WHERE checked_in_at IS NOT NULL").fetchone()[0]
        return {"permits": int(total), "checked_in": int(checked)}

    # ---- meta ------------------------------------------------------------
    def get_meta(self, key: str) -> str | None:
        with self.lock:
            r = self.conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None

    def set_meta(self, key: str, value: str) -> None:
        with self.lock:
            self.conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)", (key, value))
            self.conn.commit()

    def wipe(self) -> None:
        with self.lock:
            for table in ("events", "audit", "permits", "meta"):
                self.conn.execute(f"DELETE FROM {table}")
            self.conn.execute("DELETE FROM sqlite_sequence WHERE name='events'")
            self.conn.commit()

    def close(self) -> None:
        with self.lock:
            self.conn.close()
