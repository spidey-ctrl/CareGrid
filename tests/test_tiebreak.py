from collections.abc import Callable, Sequence
from datetime import timedelta

import pytest

from conftest import T0

from caregrid import Engine, EntryView, ManualClock, Sofa, SurvivalPrediction


class MapSurvivalModel:
    """Per-severity survival probabilities, so tests can stage near-ties by hand."""

    def __init__(self, probabilities: dict[int, float]) -> None:
        self.probabilities = probabilities

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        return SurvivalPrediction(
            probability=self.probabilities[sofa.severity()], attribution={}
        )


class SequentialModel:
    """Survival probabilities handed out in registration order."""

    def __init__(self, probabilities: Sequence[float]) -> None:
        self.probabilities = probabilities
        self.next = 0

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        probability = self.probabilities[self.next]
        self.next += 1
        return SurvivalPrediction(probability=probability, attribution={})


def _ids(engine: Engine) -> list[str]:
    return [e.patient_id for e in engine.current_queue().entries]


def _by_patient(engine: Engine, patient_id: str) -> EntryView:
    return next(e for e in engine.current_queue().entries if e.patient_id == patient_id)


def _register(engine: Engine, sofa: Sofa, age: int = 60) -> str:
    patient_id = engine.register_patient(sofa=sofa, age=age, comorbidities=())
    engine.open_entry(patient_id)
    return patient_id


def _engine(survival: dict[int, float], clock: ManualClock) -> Engine:
    return Engine(
        survival_model=MapSurvivalModel(survival), clock=clock, wait_horizon=timedelta(hours=24)
    )


def test_cascade_breaks_a_two_decimal_tie_by_severity(clock: ManualClock) -> None:
    engine = _engine({13: 0.7, 12: 0.7}, clock)
    milder = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # severity 12
    clock.advance(timedelta(hours=7))
    severe = _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # severity 13, waits 0h

    queue = engine.current_queue()
    top = queue.entries[0]

    assert _ids(engine) == [severe, milder]
    assert round(queue.entries[0].score, 2) == round(queue.entries[1].score, 2)
    assert top.patient_id == severe
    assert top.tie_break_reason == "tie-break: higher severity (0.542 vs 0.500)"
    assert queue.entries[1].tie_break_reason is None


def test_entries_several_decimals_apart_skip_the_cascade(clock: ManualClock) -> None:
    engine = _engine({13: 0.7, 12: 0.7, 6: 0.7}, clock)
    severe = _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # 0.481 -> 0.48
    clock.advance(timedelta(hours=7))
    milder = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # 0.477 -> 0.48
    clock.advance(timedelta(hours=23))
    healthy = _register(engine, Sofa(1, 1, 1, 1, 1, 1))  # severity 6, waits 0h

    entries = engine.current_queue().entries

    assert [e.patient_id for e in entries] == [severe, milder, healthy]
    assert entries[2].tie_break_reason is None


def test_cascade_resolves_by_survival_when_severity_ties(clock: ManualClock) -> None:
    engine = Engine(
        survival_model=SequentialModel([0.7, 0.68]),
        clock=clock,
        wait_horizon=timedelta(hours=24),
    )
    high_survival = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # p=0.7
    low_survival = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # p=0.68
    clock.advance(timedelta(hours=2))  # both accrue 2h wait

    top = engine.current_queue().entries[0]

    assert round(engine.current_queue().entries[1].score, 2) == round(top.score, 2)
    assert _ids(engine) == [high_survival, low_survival]
    assert top.tie_break_reason == "tie-break: higher survival (0.700 vs 0.680)"


def test_cascade_resolves_by_longer_wait_when_severity_and_survival_tie(
    clock: ManualClock,
) -> None:
    engine = _engine({12: 0.7}, clock)
    long_wait = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    clock.advance(timedelta(hours=2))
    short_wait = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    clock.advance(timedelta(hours=4))  # snapshot: long_wait waited 6h, short_wait 4h

    top = engine.current_queue().entries[0]

    assert round(engine.current_queue().entries[1].score, 2) == round(top.score, 2)
    assert _ids(engine) == [long_wait, short_wait]
    assert top.tie_break_reason == "tie-break: longer wait (6h vs 4h)"


def test_cascade_resolves_by_earlier_entry_when_clinicals_and_wait_saturate(
    clock: ManualClock,
) -> None:
    engine = _engine({12: 0.7}, clock)
    earlier = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    clock.advance(timedelta(hours=12))
    later = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    clock.advance(timedelta(hours=36))  # both now past the 24h saturation

    engine.current_queue()
    top = engine.current_queue().entries[0]

    assert _ids(engine) == [earlier, later]
    assert top.tie_break_reason == "tie-break: earlier entry (2026-01-01T08:00:00+00:00)"


def test_repeating_the_query_is_deterministic_and_replayable(clock: ManualClock) -> None:
    engine = _engine({13: 0.7, 12: 0.7}, clock)
    milder = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    clock.advance(timedelta(hours=7))
    severe = _register(engine, Sofa(3, 3, 2, 2, 2, 1))

    first = [(e.patient_id, e.tie_break_reason) for e in engine.current_queue().entries]
    second = [(e.patient_id, e.tie_break_reason) for e in engine.current_queue().entries]

    assert second == first
    assert _ids(engine) == [severe, milder]
    assert first[0] == (severe, "tie-break: higher severity (0.542 vs 0.500)")


def test_identical_queue_on_fresh_engine_orders_identically() -> None:
    def build() -> Engine:
        clock = ManualClock(T0)
        engine = _engine({13: 0.7, 12: 0.7}, clock)
        _register(engine, Sofa(3, 3, 2, 2, 2, 1))
        clock.advance(timedelta(hours=7))
        _register(engine, Sofa(2, 2, 2, 2, 2, 2))
        return engine

    original = build()
    replay = build()

    assert [e.patient_id for e in original.current_queue().entries] == [
        e.patient_id for e in replay.current_queue().entries
    ]