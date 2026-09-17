"""Silent Seal — signed Batch Pass, carried in a QR or on paper.

Payload (no PII): ``{v, batch, point, lane, protected_until, issued_at}``
→ canonical JSON → signature → envelope → zlib → Base45 (RFC 9285).

Base45's alphabet is exactly the QR alphanumeric set, so the pass fits in a
small QR. Verification is offline and constant time: Ed25519 when the
``cryptography`` package imports, otherwise HMAC-SHA256 with a clearly named
``scheme`` so nobody mistakes one for the other.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import zlib
from dataclasses import dataclass

try:  # optional dependency, decided once at import time
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ed25519 as _ed

    _HAVE_ED25519 = True
except Exception:  # pragma: no cover - depends on the host
    _HAVE_ED25519 = False

PASS_VERSION = 1
PASS_PREFIX = "HWN1:"
SCHEME_ED25519 = "ed25519"
SCHEME_HMAC = "hmac-sha256"

_B45 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
_B45_INDEX = {c: i for i, c in enumerate(_B45)}


class SealError(ValueError):
    pass


# ---- Base45 (RFC 9285) -----------------------------------------------------
def base45_encode(data: bytes) -> str:
    out: list[str] = []
    for i in range(0, len(data), 2):
        chunk = data[i : i + 2]
        if len(chunk) == 2:
            n = chunk[0] * 256 + chunk[1]
            c, n = n % 45, n // 45
            d, e = n % 45, n // 45
            out.append(_B45[c] + _B45[d] + _B45[e])
        else:
            n = chunk[0]
            c, d = n % 45, n // 45
            out.append(_B45[c] + _B45[d])
    return "".join(out)


def base45_decode(text: str) -> bytes:
    if len(text) % 3 == 1:
        raise SealError("invalid Base45 length")
    try:
        vals = [_B45_INDEX[c] for c in text]
    except KeyError as exc:
        raise SealError("invalid Base45 character") from exc
    out = bytearray()
    for i in range(0, len(vals), 3):
        chunk = vals[i : i + 3]
        if len(chunk) == 3:
            n = chunk[0] + chunk[1] * 45 + chunk[2] * 45 * 45
            if n > 0xFFFF:
                raise SealError("invalid Base45 triple")
            out.append(n >> 8)
            out.append(n & 0xFF)
        else:
            n = chunk[0] + chunk[1] * 45
            if n > 0xFF:
                raise SealError("invalid Base45 pair")
            out.append(n)
    return bytes(out)


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


# ---- pass payload ----------------------------------------------------------
@dataclass(frozen=True)
class PassPayload:
    batch: str
    point: str
    lane: str
    protected_until: int  # epoch seconds
    issued_at: int  # epoch seconds
    v: int = PASS_VERSION

    def to_dict(self) -> dict:
        return {
            "v": self.v,
            "batch": self.batch,
            "point": self.point,
            "lane": self.lane,
            "protected_until": int(self.protected_until),
            "issued_at": int(self.issued_at),
        }

    # Wire form uses one-letter keys so the QR stays small (version 7–8).
    _WIRE = {"v": "v", "batch": "b", "point": "p", "lane": "l", "protected_until": "u", "issued_at": "i"}

    def to_wire(self) -> dict:
        d = self.to_dict()
        return {self._WIRE[k]: d[k] for k in self._WIRE}

    @classmethod
    def from_wire(cls, w: dict) -> "PassPayload":
        if not isinstance(w, dict) or set(w) != set(cls._WIRE.values()):
            raise SealError("payload fields do not match the pass schema")
        inv = {v: k for k, v in cls._WIRE.items()}
        return cls.from_dict({inv[k]: v for k, v in w.items()})

    @classmethod
    def from_dict(cls, d: dict) -> "PassPayload":
        required = {"v", "batch", "point", "lane", "protected_until", "issued_at"}
        if not isinstance(d, dict) or set(d) != required:
            raise SealError("payload fields do not match the pass schema")
        for k in ("batch", "point", "lane"):
            if not isinstance(d[k], str) or not (1 <= len(d[k]) <= 32):
                raise SealError(f"bad field {k}")
        if d["lane"] not in ("men", "women"):
            raise SealError("bad lane")
        return cls(
            batch=d["batch"],
            point=d["point"],
            lane=d["lane"],
            protected_until=int(d["protected_until"]),
            issued_at=int(d["issued_at"]),
            v=int(d["v"]),
        )


@dataclass(frozen=True)
class VerifyResult:
    valid: bool
    reason: str  # "ok" | "expired" | "bad_signature" | "malformed" | "wrong_key" | "wrong_scheme"
    payload: PassPayload | None = None
    scheme: str = ""

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "reason": self.reason,
            "scheme": self.scheme,
            "payload": self.payload.to_dict() if self.payload else None,
        }


# ---- signer ----------------------------------------------------------------
class Signer:
    """Holds the Authority key. ``scheme`` says which primitive is active.

    The secret is derived deterministically from ``secret`` so a demo laptop
    keeps the same key across restarts. In production the Authority's
    private key lives in an HSM and only the public key is distributed.
    """

    def __init__(self, secret: bytes | str, *, key_id: str = "demo", force_scheme: str | None = None):
        if isinstance(secret, str):
            secret = secret.encode()
        if len(secret) < 16:
            raise SealError("seal secret too short")
        self.key_id = key_id
        seed = hashlib.sha256(b"hawnan-seal-v1|" + secret).digest()
        scheme = force_scheme or (SCHEME_ED25519 if _HAVE_ED25519 else SCHEME_HMAC)
        if scheme == SCHEME_ED25519 and not _HAVE_ED25519:
            raise SealError("ed25519 requested but `cryptography` is unavailable")
        self.scheme = scheme
        if scheme == SCHEME_ED25519:
            self._priv = _ed.Ed25519PrivateKey.from_private_bytes(seed)
            self._pub = self._priv.public_key()
            self.public_key_hex = self._pub.public_bytes_raw().hex()
        elif scheme == SCHEME_HMAC:
            self._mac_key = seed
            self.public_key_hex = ""
        else:
            raise SealError(f"unknown scheme {scheme}")

    @classmethod
    def from_env(cls, env: dict | None = None) -> "Signer":
        env = os.environ if env is None else env
        secret = env.get("HAWNAN_SEAL_SECRET", "hawnan-demo-seal-secret-2026-change-me")
        force = env.get("HAWNAN_SEAL_SCHEME") or None
        return cls(secret, key_id=env.get("HAWNAN_SEAL_KEY_ID", "team-2026"), force_scheme=force)

    # -- primitives
    def _sign(self, message: bytes) -> bytes:
        if self.scheme == SCHEME_ED25519:
            return self._priv.sign(message)
        return hmac.new(self._mac_key, message, hashlib.sha256).digest()

    def _verify(self, message: bytes, sig: bytes) -> bool:
        if self.scheme == SCHEME_ED25519:
            try:
                self._pub.verify(sig, message)
                return True
            except InvalidSignature:
                return False
        expected = hmac.new(self._mac_key, message, hashlib.sha256).digest()
        return hmac.compare_digest(expected, sig)

    # -- pass
    def issue(self, payload: PassPayload) -> str:
        """JSON → signature → zlib → Base45. The signature (raw bytes) follows the zlib stream."""
        body = {"s": self.scheme, "k": self.key_id, "p": payload.to_wire()}
        message = canonical(body)
        sig = self._sign(message)
        packed = zlib.compress(message, 9) + sig
        return PASS_PREFIX + base45_encode(packed)

    def verify(self, pass_text: str, now: float | None = None) -> VerifyResult:
        try:
            text = pass_text.strip()
            if not text.startswith(PASS_PREFIX) or len(text) > 1024:
                return VerifyResult(False, "malformed", scheme=self.scheme)
            raw = base45_decode(text[len(PASS_PREFIX):])
            d = zlib.decompressobj()
            message = d.decompress(raw, 4096)
            if not d.eof:
                return VerifyResult(False, "malformed", scheme=self.scheme)
            sig = d.unused_data
            env = json.loads(message)
            if not isinstance(env, dict) or set(env) != {"s", "k", "p"}:
                return VerifyResult(False, "malformed", scheme=self.scheme)
            payload = PassPayload.from_wire(env["p"])
        except (SealError, ValueError, TypeError, KeyError, zlib.error):
            return VerifyResult(False, "malformed", scheme=self.scheme)
        if env["s"] != self.scheme:
            return VerifyResult(False, "wrong_scheme", scheme=self.scheme)
        if not hmac.compare_digest(str(env["k"]).encode(), self.key_id.encode()):
            return VerifyResult(False, "wrong_key", scheme=self.scheme)
        if canonical(env) != message or not self._verify(message, sig):
            return VerifyResult(False, "bad_signature", scheme=self.scheme)
        if now is not None and now > payload.protected_until:
            return VerifyResult(False, "expired", payload, scheme=self.scheme)
        return VerifyResult(True, "ok", payload, scheme=self.scheme)

    def describe(self) -> dict:
        return {
            "scheme": self.scheme,
            "key_id": self.key_id,
            "public_key_hex": self.public_key_hex,
            "ed25519_available": _HAVE_ED25519,
        }


def ed25519_available() -> bool:
    return _HAVE_ED25519
