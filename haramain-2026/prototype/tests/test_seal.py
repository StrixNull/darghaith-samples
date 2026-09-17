import pytest

from hawnan_core.seal import (
    SCHEME_ED25519,
    SCHEME_HMAC,
    PassPayload,
    SealError,
    Signer,
    base45_decode,
    base45_encode,
    ed25519_available,
)

PAYLOAD = PassPayload(batch="W1-014", point="W1", lane="women", protected_until=1_800_000_900, issued_at=1_800_000_000)


def test_base45_roundtrip_and_known_vector():
    assert base45_encode(b"AB") == "BB8"
    assert base45_encode(b"Hello!!") == "%69 VD92EX0"
    for raw in (b"", b"\x00", b"\xff\xff", bytes(range(256))):
        assert base45_decode(base45_encode(raw)) == raw
    with pytest.raises(SealError):
        base45_decode("abc")  # lowercase is not in the alphabet


@pytest.mark.parametrize("scheme", [SCHEME_HMAC] + ([SCHEME_ED25519] if ed25519_available() else []))
def test_issue_and_verify(scheme):
    s = Signer("unit-test-secret-0123456789", key_id="t", force_scheme=scheme)
    text = s.issue(PAYLOAD)
    assert text.startswith("HWN1:")
    assert set(text[5:]) <= set("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:")
    r = s.verify(text, now=1_800_000_100)
    assert r.valid and r.reason == "ok" and r.payload == PAYLOAD and r.scheme == scheme
    assert len(text) < 260  # fits a version-9 alphanumeric QR


def test_tampered_pass_is_rejected():
    s = Signer("unit-test-secret-0123456789", force_scheme=SCHEME_HMAC)
    text = s.issue(PAYLOAD)
    flipped = text[:-6] + ("A" if text[-6] != "A" else "B") + text[-5:]
    assert s.verify(flipped).reason in ("bad_signature", "malformed")
    assert not s.verify("HWN1:" + text[5:][::-1]).valid
    assert s.verify("garbage").reason == "malformed"
    assert s.verify("").reason == "malformed"


def test_expiry_uses_protected_until():
    s = Signer("unit-test-secret-0123456789", force_scheme=SCHEME_HMAC)
    text = s.issue(PAYLOAD)
    assert s.verify(text, now=PAYLOAD.protected_until).valid
    r = s.verify(text, now=PAYLOAD.protected_until + 1)
    assert not r.valid and r.reason == "expired" and r.payload is not None


def test_other_key_or_scheme_is_rejected():
    a = Signer("unit-test-secret-0123456789", key_id="a", force_scheme=SCHEME_HMAC)
    b = Signer("another-secret-9876543210", key_id="a", force_scheme=SCHEME_HMAC)
    c = Signer("unit-test-secret-0123456789", key_id="c", force_scheme=SCHEME_HMAC)
    text = a.issue(PAYLOAD)
    assert b.verify(text).reason == "bad_signature"
    assert c.verify(text).reason == "wrong_key"
    if ed25519_available():
        e = Signer("unit-test-secret-0123456789", key_id="a", force_scheme=SCHEME_ED25519)
        assert e.verify(text).reason == "wrong_scheme"
        assert e.describe()["public_key_hex"] and e.scheme == SCHEME_ED25519


def test_payload_contains_no_pii_fields():
    assert set(PAYLOAD.to_dict()) == {"v", "batch", "point", "lane", "protected_until", "issued_at"}
    with pytest.raises(SealError):
        PassPayload.from_dict({**PAYLOAD.to_dict(), "name": "x"})
