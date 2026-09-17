import pytest

from hawnan_core.audit import GENESIS, AuditLog


def test_chain_verifies_and_head_moves():
    log = AuditLog(b"unit-test-audit-key-0123")
    assert log.head == GENESIS
    r1 = log.append("sup-1", "instruction_set", {"point": "W1", "id": "please_sit"}, ts=1.0)
    r2 = log.append("sup-1", "advance", {"batch": "W1-014"}, ts=2.0)
    assert r1.prev_hash == GENESIS and r2.prev_hash == r1.hash and log.head == r2.hash
    assert log.verify().ok and log.verify().length == 2


def test_tampering_any_record_breaks_the_chain():
    log = AuditLog(b"unit-test-audit-key-0123")
    for i in range(5):
        log.append("a", "x", {"i": i}, ts=float(i))
    records = [r.to_dict() for r in log.records]
    records[2]["detail"]["i"] = 99
    bad = AuditLog.load(b"unit-test-audit-key-0123", records)
    check = bad.verify()
    assert not check.ok and check.first_bad_seq == 3
    removed = AuditLog.load(b"unit-test-audit-key-0123", records[:2] + records[3:])
    assert not removed.verify().ok


def test_wrong_key_fails_and_short_key_rejected():
    log = AuditLog(b"unit-test-audit-key-0123")
    log.append("a", "x", {}, ts=1.0)
    other = AuditLog.load(b"another-audit-key-987654", [r.to_dict() for r in log.records])
    assert not other.verify().ok
    with pytest.raises(ValueError):
        AuditLog(b"short")
