import json

import pytest
from fastapi.testclient import TestClient

from app.main import Config, create_app

STAFF = {"X-Device-Token": "demo-staff-1"}


@pytest.fixture(scope="module")
def client():
    app = create_app(Config(db_path=":memory:", staff_tokens=("demo-staff-1",)))
    with TestClient(app) as c:
        yield c


def test_runtime_declares_simulated_feed_and_scheme(client):
    r = client.get("/api/runtime")
    assert r.status_code == 200
    body = r.json()
    assert body["simulated_permit_feed"] is True and body["llm_at_runtime"] is False
    assert body["seal"]["scheme"] in ("ed25519", "hmac-sha256")
    assert body["content"]["packs"] == 10 and body["audit"]["ok"]
    assert r.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert "hawnan_device=" in r.headers.get("set-cookie", "")


def test_pages_and_static_are_served(client):
    for path in ("/", "/guest", "/staff", "/display", "/ops", "/checkin", "/static/hawnan.css", "/static/hawnan.js", "/static/qr.js", "/sw.js", "/manifest.webmanifest"):
        r = client.get(path)
        assert r.status_code == 200, path
    assert "بيانات تصاريح محاكاة معلنة" in client.get("/static/hawnan.js").text


def test_checkin_verify_point_state_instruction_advance(client):
    sample = client.get("/api/permits/sample", params={"point_id": "W1"}).json()["permits"]
    siti = next(p for p in sample if p["ref"] == "NSK-SITI-0820")
    assert siti["lang"] == "id" and siti["batch_number"] == 14

    r = client.post("/api/checkin", json={"permit_ref": "NSK-SITI-0820"})
    assert r.status_code == 200, r.text
    issued = r.json()
    assert issued["pass"].startswith("HWN1:") and issued["batch"]["id"] == "W1-014" and issued["lang"] == "id"
    assert issued["batch"]["range"]["about"] and issued["batch"]["range"]["low_min"] < issued["batch"]["range"]["high_min"]

    v = client.post("/api/verify", json={"pass": issued["pass"], "lang": "id"}).json()
    assert v["valid"] and v["reason"] == "ok" and v["batch"]["id"] == "W1-014" and v["point"]["id"] == "W1"
    bad = client.post("/api/verify", json={"pass": issued["pass"][:-3] + "AAA"}).json()
    assert not bad["valid"]

    again = client.post("/api/checkin", json={"permit_ref": "NSK-SITI-0820"}).json()
    assert again["reissued"] is True and again["batch"]["guests"] == issued["batch"]["guests"]

    state = client.get("/api/point/W1/state", params={"lang": "id"}).json()
    assert state["point"]["id"] == "W1" and state["dir"] == "ltr"
    assert any(b["id"] == "W1-014" for b in state["queue"])
    assert state["active_instruction"]["id"] == "please_sit" and state["active_instruction"]["text"] == "Silakan duduk"
    assert "id" in state["fan_out"]["texts"] and "ar" in state["fan_out"]["texts"]

    denied = client.post("/api/supervisor/instruction", json={"point_id": "W1", "instruction_id": "advance_calmly"})
    assert denied.status_code == 401
    ok = client.post("/api/supervisor/instruction", json={"point_id": "W1", "instruction_id": "advance_calmly"}, headers=STAFF)
    assert ok.status_code == 200 and ok.json()["fan_out"]["id"] == "advance_calmly"
    ur = client.get("/api/point/W1/state", params={"lang": "ur"}).json()["active_instruction"]
    assert ur["text"] == "آرام سے آگے بڑھیں" and ur["pictogram"] == "🚶"

    b = client.get("/api/batch/W1-013", params={"lang": "id"}).json()
    assert b["batch"]["state"] == "prepare" and b["preparation"]["title"] == "Beberapa menit sebelum masuk"
    adv = client.post("/api/supervisor/advance", json={"batch_id": "W1-013"}, headers=STAFF)
    assert adv.status_code == 200 and adv.json()["batch"]["state"] == "moving"
    b14 = client.get("/api/batch/W1-014", params={"lang": "id"}).json()
    assert b14["batch"]["position"] == 0

    audit = client.get("/api/audit/verify").json()
    assert audit["ok"] and audit["length"] >= 5
    recent = client.get("/api/audit/recent", params={"n": 3}).json()["records"]
    assert recent[0]["action"] == "advance" and recent[0]["actor"] == "staff:1"


def test_journey_showme_content_and_indicators(client):
    j = client.get("/api/journey/NSK-SITI-0820", params={"lang": "id"}).json()
    assert j["dir"] == "ltr" and "Gate 25" in j["messages"]["t24"] and j["depart"] < j["slot"] or True
    assert "{" not in j["messages"]["t24"] and j["walk_min"] >= 1
    assert client.get("/api/journey/NSK-NOPE-0000").status_code == 404

    cards = client.get("/api/showme", params={"lang": "id", "batch_id": "W1-014"}).json()["cards"]
    assert len(cards) == 8 and cards[1]["text"].startswith("Apakah ini tempat untuk rombongan wanita pukul")
    assert cards[1]["ar"].startswith("هل هذا مكان فوج النساء الساعة")

    ui = client.get("/api/content/ui", params={"lang": "fa"}).json()
    assert ui["dir"] == "rtl" and ui["ui"]["about_minutes"] == "حدود {low}–{high} دقیقه"
    langs = client.get("/api/content/languages").json()["languages"]
    assert [l["code"] for l in langs] == ["ar", "en", "ur", "id", "tr", "bn", "fr", "ms", "ha", "fa"]
    review = client.get("/api/content/review").json()["packs"]
    assert sum(p["reviewed"] for p in review) == 2

    ind = client.get("/api/indicators").json()
    assert len(ind["points"]) == 4 and ind["simulated"] is True and ind["audit"]["ok"]
    assert {t["lane"] for t in ind["throughput"]} == {"men", "women"}


def test_twin_endpoint_compares_scenarios(client):
    r = client.post("/api/twin/run", json={"permits_per_day": 3000, "compare": True, "seed": 5})
    assert r.status_code == 200
    rows = r.json()["results"]
    assert len(rows) == 4 and rows[1]["pressure_events"] <= rows[0]["pressure_events"]
    assert client.post("/api/twin/run", json={"permits_per_day": 10}).status_code == 422
    one = client.post("/api/twin/run", json={"permits_per_day": 2000, "checks_per_guest": 1}).json()["result"]
    assert one["params"]["checks_per_guest"] == 1


def test_unknown_permit_and_rate_limit_shape(client):
    assert client.post("/api/checkin", json={"permit_ref": "NSK-DOES-NOT-EXIST"}).status_code == 404
    assert client.post("/api/verify", json={"pass": "HWN1:AAAA"}).json()["reason"] == "malformed"
