from dataclasses import FrozenInstanceError
from datetime import timedelta
from collections.abc import Callable

import pytest

from conftest import MapSurvivalModel, T0

from caregrid import (
    BALANCED,
    Engine,
    ManualClock,
    SEVERITY_DOMINANT,
    SEVERITY_HEAVY,
    Sofa,
    UnknownPatient,
    UnknownSnapshot,
)


def _engine(clock: ManualClock) -> Engine:
    return Engine(
        survival_model=MapSurvivalModel({16: 0.6, 6: 0.7}),
        clock=clock,
        wait_horizon=timedelta(hours=24),
    )


def _register(engine: Engine, sofa: Sofa) -> str:
    patient_id = engine.register_patient(sofa=sofa, age=60, comorbidities=())
    engine.open_entry(patient_id)
    return patient_id


def test_snapshots_append_in_creation_order(clock: ManualClock) -> None:
    engine = Engine(survival_model=MapSurvivalModel({12: 0.7}), clock=clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    first = engine.snapshot("initial")
    clock.advance(timedelta(hours=30))
    second = engine.snapshot("wait-elapsed")
    engine.set_profile(BALANCED)
    third = engine.snapshot("profile-change")

    trail = engine.trail()

    assert [s.snapshot_id for s in trail] == [1, 2, 3]
    assert [s.captured_at for s in trail] == [
        first.captured_at,
        second.captured_at,
        third.captured_at,
    ]
    assert trail == (first, second, third)


def test_snapshot_carries_full_score_breakdown_and_attribution(
    engine_factory: Callable[..., Engine], clock: ManualClock
) -> None:
    engine = engine_factory(clock=clock, wait_horizon=timedelta(hours=24))
    patient_id = engine.register_patient(
        sofa=Sofa(3, 1, 2, 2, 3, 1), age=64, comorbidities=("diabetes",)
    )
    engine.open_entry(patient_id)
    clock.advance(timedelta(hours=30))

    snap = engine.snapshot("wait-elapsed")
    top = snap.entries[0]

    assert snap.trigger == "wait-elapsed"
    assert snap.profile == SEVERITY_DOMINANT
    assert snap.wait_horizon == timedelta(hours=24)
    assert snap.captured_at == clock.now()
    assert top.patient_id == patient_id
    assert top.severity_factor == pytest.approx(12 / 24)
    assert top.survival_factor == pytest.approx(0.7)
    assert top.waiting_factor == pytest.approx(1.0)
    assert top.waiting_time == timedelta(hours=30)
    assert top.survival_probability == pytest.approx(0.7)
    assert top.survival_attribution == {"sofa_total": 0.1, "age": 0.05}


def test_snapshot_records_tie_break_reasoning(clock: ManualClock) -> None:
    engine = Engine(survival_model=MapSurvivalModel({13: 0.7, 12: 0.7}), clock=clock)
    milder = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # severity 12
    clock.advance(timedelta(hours=7))
    severe = _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # severity 13

    snap = engine.snapshot("initial")

    assert [e.patient_id for e in snap.entries] == [severe, milder]
    assert snap.entries[0].tie_break_reason == "tie-break: higher severity (0.542 vs 0.500)"

    assert engine.trail()[0] is snap


def test_trail_is_append_only(clock: ManualClock) -> None:
    engine = Engine(survival_model=MapSurvivalModel({12: 0.7}), clock=clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    snap = engine.snapshot("initial")
    engine.snapshot("re-run")

    with pytest.raises(FrozenInstanceError):
        setattr(snap, "entries", ())
    with pytest.raises(FrozenInstanceError):
        setattr(snap.entries[0], "score", 1.0)
    assert engine.trail()[0] is snap  # earlier record untouched by later snapshot


def test_reviewer_recovers_exact_past_rerank(clock: ManualClock) -> None:
    engine = Engine(survival_model=MapSurvivalModel({12: 0.7}), clock=clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    first = engine.snapshot("initial")
    clock.advance(timedelta(hours=30))
    second = engine.snapshot("wait-elapsed")

    recovered = engine.snapshot_at(1)

    assert recovered is first
    assert recovered is not second
    assert [e.patient_id for e in recovered.entries] == [e.patient_id for e in first.entries]
    assert recovered.captured_at == first.captured_at
    with pytest.raises(UnknownSnapshot):
        engine.snapshot_at(99)


def test_patient_rank_history_tracks_movement_across_snapshots(clock: ManualClock) -> None:
    engine = _engine(clock)
    long_waiter = _register(engine, Sofa(1, 1, 1, 1, 1, 1))  # severity 6
    clock.advance(timedelta(hours=24))
    sick = _register(engine, Sofa(3, 3, 3, 3, 2, 2))  # severity 16, waits 0h

    engine.snapshot("initial")  # Severity-dominant: long-waiter wins on waiting
    engine.set_profile(SEVERITY_HEAVY)
    engine.snapshot("profile-change")  # sick patient now beats the long-waiter

    sick_history = engine.patient_rank_history(sick)
    waiter_history = engine.patient_rank_history(long_waiter)

    assert [(s.snapshot_id, rank) for s, rank in sick_history] == [(1, 2), (2, 1)]
    assert [(s.snapshot_id, rank) for s, rank in waiter_history] == [(1, 1), (2, 2)]
    with pytest.raises(UnknownPatient):
        engine.patient_rank_history("no-such-patient")