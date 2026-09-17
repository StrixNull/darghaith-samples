import pytest

from hawnan_core.twin import TwinParams, compare, run

BASE = dict(permits_per_day=6000, points=4, seed=11)


def test_same_seed_same_results():
    a = run({**BASE, "checks_per_guest": 3})
    b = run({**BASE, "checks_per_guest": 3})
    assert a == b
    assert a.guests == 6000 and a.batches == 4 * 30


def test_one_check_reduces_pressure_proxy():
    three = run({**BASE, "checks_per_guest": 3})
    one = run({**BASE, "checks_per_guest": 1})
    assert one.pressure_events < three.pressure_events
    assert one.mean_wait_min <= three.mean_wait_min


def test_staggered_windows_reduce_wait_and_pressure():
    burst = run({**BASE, "checks_per_guest": 1, "staggered_windows": False})
    calm = run({**BASE, "checks_per_guest": 1, "staggered_windows": True})
    assert calm.mean_wait_min < burst.mean_wait_min
    assert calm.pressure_events <= burst.pressure_events
    assert calm.rebatched_guests <= burst.rebatched_guests


def test_result_is_serialisable_and_bounded():
    r = run(BASE).to_dict()
    assert 0 <= r["batches_on_time_pct"] <= 100 and r["p90_wait_min"] >= r["mean_wait_min"] * 0.5
    assert r["params"]["seed"] == 11


def test_param_validation():
    with pytest.raises(ValueError):
        TwinParams.from_dict({"permits_per_day": 10})
    with pytest.raises(ValueError):
        TwinParams.from_dict({"checks_per_guest": 4})


def test_compare_returns_four_labelled_scenarios():
    rows = compare({**BASE, "permits_per_day": 2000})
    assert [r["label"] for r in rows] == [
        "3 checks · no windows",
        "1 check · no windows",
        "3 checks · staggered windows",
        "1 check · staggered windows",
    ]
