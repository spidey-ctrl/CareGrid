from dataclasses import FrozenInstanceError
from datetime import timedelta

import pytest

from conftest import T0

from caregrid import (
    ArbitrationOutcome,
    Engine,
    Event,
    EventKind,
    ManualClock,
    Sofa,
    SurvivalPrediction,
    WeightProfile,
)


class FakeSurvivalModel:
    """Constant survival so event assertions are independent of scoring."""

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        return SurvivalPrediction(probability=0.7, attribution={})


def _engine(clock: ManualClock) -> Engine:
    return Engine(survival_model=FakeSurvivalModel(), clock=clock)


def _register(engine: Engine, sofa: Sofa) -> str:
    patient_id = engine.register_patient(sofa=sofa, age=60, comorbidities=())
    engine.open_entry(patient_id)
    return patient_id


def test_arrival_events_record_each_open_entry(clock: ManualClock) -> None:
    engine = _engine(clock)
    patient_id = _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    events = engine.events()

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, Event)
    assert event.kind is EventKind.ARRIVAL
    assert event.occurred_at == T0
    assert patient_id in event.detail


def test_removal_event_records_the_closed_entry(clock: ManualClock) -> None:
    engine = _engine(clock)
    patient_id = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    entry_id = engine.open_entry(patient_id)
    engine.events()

    engine.close_entry(entry_id)

    event = engine.events()[-1]
    assert event.kind is EventKind.REMOVAL
    assert entry_id in event.detail


def test_profile_change_is_reported(clock: ManualClock) -> None:
    engine = _engine(clock)

    engine.set_profile(WeightProfile("Balanced", 0.4, 0.3, 0.3))

    event = engine.events()[-1]
    assert event.kind is EventKind.PROFILE_CHANGE
    assert "Balanced" in event.detail


def test_every_snapshot_emits_a_rerank_event(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    engine.snapshot("initial")
    clock.advance(timedelta(hours=1))
    engine.snapshot("wait-elapsed")

    reranks = [e for e in engine.events() if e.kind is EventKind.RERANK]
    assert [e.detail for e in reranks] == [
        "re-ranked 1 entries — trigger: initial",
        "re-ranked 1 entries — trigger: wait-elapsed",
    ]


def test_confirmation_reports_allocation_and_removal(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    decision = engine.confirm_allocation(engine.recommend())

    kinds = [e.kind for e in engine.events()]
    assert decision.outcome is ArbitrationOutcome.CONFIRMED
    assert kinds == [
        EventKind.ARRIVAL,
        EventKind.BED_FREED,
        EventKind.ALLOCATION,
        EventKind.REMOVAL,
    ]
    assert "allocated" in engine.events()[2].detail


def test_recommend_reports_the_freed_bed_and_top_candidate(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    recommendation = engine.recommend()

    event = engine.events()[-1]
    assert event.kind is EventKind.BED_FREED
    assert recommendation.entry.patient_id in event.detail


def test_events_are_append_only_and_immutable(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    first = engine.events()[0]
    engine.snapshot("initial")

    with pytest.raises(FrozenInstanceError):
        setattr(first, "detail", "tampered")
    assert len(engine.events()) == 2
    assert engine.events()[0] is first


def test_events_are_recorded_in_occurrence_order(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    clock.advance(timedelta(hours=2))
    _register(engine, Sofa(3, 3, 2, 2, 2, 1))

    events = engine.events()

    assert [e.occurred_at for e in events] == [T0, T0 + timedelta(hours=2)]
    assert events[0].id < events[1].id