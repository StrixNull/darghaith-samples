import pytest

from hawnan_core.batch_clock import BatchClock, Event, InvalidTransition, STATES, UnknownBatch


def make_clock():
    c = BatchClock()
    c.define_point("M1", "men", 0.0, name_en="Point 1")
    c.create_batch("M1-001", "M1", 1000.0, 0.0, number=1)
    return c


def test_full_flow_in_order():
    c = make_clock()
    c.check_in_guest("M1-001", 10.0, lang="id")
    assert c.batches["M1-001"].state == "checked_in"
    for state in ("holding", "prepare", "moving", "inside", "exited"):
        c.set_state("M1-001", state, 20.0)
    b = c.batches["M1-001"]
    assert b.state == "exited"
    assert [s for s, _ in b.history] == list(STATES)


def test_skipping_a_state_is_rejected():
    c = make_clock()
    with pytest.raises(InvalidTransition):
        c.set_state("M1-001", "holding", 5.0)  # issued → holding skips checked_in


def test_backwards_transition_is_rejected():
    c = make_clock()
    c.check_in_guest("M1-001", 1.0)
    c.set_state("M1-001", "holding", 2.0)
    with pytest.raises(InvalidTransition):
        c.set_state("M1-001", "checked_in", 3.0)


def test_exited_is_terminal():
    c = make_clock()
    c.check_in_guest("M1-001", 1.0)
    for st in ("holding", "prepare", "moving", "inside", "exited"):
        c.set_state("M1-001", st, 2.0)
    with pytest.raises(InvalidTransition):
        c.advance("M1-001", 3.0)


def test_timestamps_cannot_go_backwards():
    c = make_clock()
    c.check_in_guest("M1-001", 50.0)
    with pytest.raises(InvalidTransition):
        c.set_state("M1-001", "holding", 40.0)


def test_unknown_batch_and_duplicate_batch():
    c = make_clock()
    with pytest.raises(UnknownBatch):
        c.advance("nope", 1.0)
    with pytest.raises(Exception):
        c.create_batch("M1-001", "M1", 1000.0, 0.0)


def test_fold_rebuilds_identical_state():
    c = make_clock()
    c.check_in_guest("M1-001", 1.0, lang="ur")
    c.set_state("M1-001", "holding", 2.0)
    c.set_instruction("M1", "please_sit", 3.0, actor="sup-1")
    rebuilt = BatchClock.fold(Event.from_dict(e.to_dict()) for e in c.events)
    assert rebuilt.batches["M1-001"].to_dict() == c.batches["M1-001"].to_dict()
    assert rebuilt.points["M1"].active_instruction_id == "please_sit"
    assert rebuilt.points["M1"].instruction_seq == 1


def test_queue_order_and_position():
    c = BatchClock()
    c.define_point("W1", "women", 0.0)
    for n in (1, 2, 3):
        c.create_batch(f"W1-00{n}", "W1", 1000.0 + n * 480, 0.0, number=n)
    c.check_in_guest("W1-001", 1.0)
    for st in ("holding", "prepare", "moving"):
        c.set_state("W1-001", st, 2.0)
    assert [b.number for b in c.queue("W1")] == [2, 3]
    assert c.position("W1-003") == 1
    assert c.position("W1-002") == 0


def test_release_intervals_and_stage_durations():
    c = BatchClock()
    c.define_point("M2", "men", 0.0)
    t = 0.0
    for n in range(1, 5):
        bid = f"M2-{n:03d}"
        c.create_batch(bid, "M2", 100.0 * n, 0.0, number=n)
        c.check_in_guest(bid, t + 1)
        c.set_state(bid, "holding", t + 10)
        c.set_state(bid, "prepare", t + 20)
        c.set_state(bid, "moving", t + 30)
        t += 480
    assert c.release_intervals("M2") == [480.0, 480.0, 480.0]
    assert c.batches["M2-001"].stage_durations()["hold"] == 10.0
