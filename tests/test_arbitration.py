from dataclasses import FrozenInstanceError
from datetime import timedelta
from collections.abc import Callable

import pytest

from conftest import MapSurvivalModel, T0

from caregrid import (
    ArbitrationOutcome,
    EmptyQueue,
    Engine,
    InvalidDeviation,
    ManualClock,
    RankingSnapshot,
    Recommendation,
    Sofa,
    StaleRecommendation,
    UnknownEntry,
)


def _engine(clock: ManualClock) -> Engine:
    return Engine(
        survival_model=MapSurvivalModel({12: 0.7, 13: 0.6, 6: 0.8}),
        clock=clock,
        wait_horizon=timedelta(hours=24),
    )


def _register(engine: Engine, sofa: Sofa) -> str:
    patient_id = engine.register_patient(sofa=sofa, age=60, comorbidities=())
    engine.open_entry(patient_id)
    return patient_id


def test_recommend_names_the_top_ranked_entry_with_reasoning(
    clock: ManualClock, engine_factory: Callable[..., Engine]
) -> None:
    engine = engine_factory(clock=clock, wait_horizon=timedelta(hours=24))
    patient_id = engine.register_patient(sofa=Sofa(3, 1, 2, 2, 3, 1), age=64, comorbidities=())
    engine.open_entry(patient_id)

    recommendation = engine.recommend()

    assert isinstance(recommendation, Recommendation)
    assert recommendation.entry.entry_id is not None
    assert recommendation.entry.patient_id == patient_id
    assert recommendation.entry.score == pytest.approx(0.5 * (12 / 24) + 0.3 * 0.7)
    assert patient_id in recommendation.reasoning
    assert "priority score" in recommendation.reasoning


def test_recommendation_carries_the_full_ranked_queue(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # severity 12, survival 0.7
    clock.advance(timedelta(hours=6))
    _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # severity 13, survival 0.6

    recommendation = engine.recommend()

    assert len(recommendation.queue) == 2
    assert recommendation.queue[0].patient_id == recommendation.entry.patient_id


def test_recommendation_alone_allocates_nothing(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    engine.recommend()

    assert len(engine.current_queue().entries) == 1
    assert engine.trail() == ()


def test_recommend_with_empty_queue_is_rejected(clock: ManualClock) -> None:
    engine = _engine(clock)

    with pytest.raises(EmptyQueue):
        engine.recommend()


def test_confirm_records_the_allocation_and_frees_the_bed(clock: ManualClock) -> None:
    engine = _engine(clock)
    patient_id = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    recommendation = engine.recommend()

    decision = engine.confirm_allocation(recommendation)

    assert decision.outcome is ArbitrationOutcome.CONFIRMED
    assert decision.allocated.patient_id == patient_id
    assert decision.allocated.entry_id == recommendation.entry.entry_id
    assert decision.recommended == decision.allocated
    assert decision.reasoning == recommendation.reasoning
    assert decision.allocated.patient_id in decision.reasoning
    assert [e.patient_id for e in engine.current_queue().entries] == []


def test_confirm_leaves_non_allocated_entries_in_the_queue(clock: ManualClock) -> None:
    engine = _engine(clock)
    severe = _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # severity 13, survival 0.6
    milder = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # severity 12, survival 0.7
    # milder wins 0.5*0.5+0.3*0.7 = 0.460 > 0.5*0.5417+0.3*0.6 = 0.451
    recommendation = engine.recommend()

    decision = engine.confirm_allocation(recommendation)

    remaining = [e.patient_id for e in engine.current_queue().entries]
    assert decision.allocated.patient_id == milder
    assert remaining == [severe]


def test_confirm_records_the_recommendation_itself(clock: ManualClock) -> None:
    engine = _engine(clock)
    patient_id = _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    recommendation = engine.recommend()

    decision = engine.confirm_allocation(recommendation)

    assert decision.recommended.entry_id == recommendation.entry.entry_id
    assert decision.recommended.patient_id == patient_id
    assert decision.recommended.score == recommendation.entry.score


def test_confirm_lands_in_the_same_append_only_trail_as_snapshots(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    engine.snapshot("initial")
    recommendation = engine.recommend()

    decision = engine.confirm_allocation(recommendation)
    engine.snapshot("post-allocation")

    assert engine.trail() == (
        engine.snapshot_at(1),
        decision,
        engine.snapshot_at(3),
    )
    assert engine.decision_at(2) is decision
    assert [s.snapshot_id for s in engine.trail() if isinstance(s, RankingSnapshot)] == [1, 3]


def test_confirm_notes_are_recorded(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    decision = engine.confirm_allocation(engine.recommend(), note="clinician's note")

    assert decision.note == "clinician's note"


def test_reconfirming_a_stale_recommendation_is_rejected(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    recommendation = engine.recommend()
    engine.confirm_allocation(recommendation)

    with pytest.raises(StaleRecommendation):
        engine.confirm_allocation(recommendation)


def test_deviation_records_the_clinicians_choice_and_bed_goes_to_them(
    clock: ManualClock,
) -> None:
    engine = _engine(clock)
    severe = _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # severity 13, survival 0.6
    milder = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # severity 12, survival 0.7 → top
    recommendation = engine.recommend()

    severe_entry = next(
        e.entry_id
        for e in recommendation.queue
        if e.patient_id == severe
    )
    decision = engine.deviate_allocation(recommendation, severe_entry, note="familial concern")

    assert decision.outcome is ArbitrationOutcome.DEVIATION
    assert decision.allocated.patient_id == severe
    assert decision.recommended.patient_id == milder
    assert decision.allocated.entry_id != decision.recommended.entry_id
    assert decision.note == "familial concern"
    assert [e.patient_id for e in engine.current_queue().entries] == [milder]


def test_deviation_lands_in_the_trail_like_any_decision(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    clock.advance(timedelta(hours=1))
    chosen = _register(engine, Sofa(1, 1, 1, 1, 1, 1))
    recommendation = engine.recommend()
    chosen_entry = next(
        e.entry_id for e in recommendation.queue if e.patient_id == chosen
    )

    decision = engine.deviate_allocation(recommendation, chosen_entry)

    assert engine.decision_at(decision.decision_id) is decision
    assert engine.trail()[-1] is decision


def test_deviation_to_unknown_entry_is_rejected(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    recommendation = engine.recommend()

    with pytest.raises(UnknownEntry):
        engine.deviate_allocation(recommendation, "no-such-entry")


def test_deviation_to_the_recommended_entry_is_rejected(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))
    recommendation = engine.recommend()

    with pytest.raises(InvalidDeviation, match="confirm"):
        engine.deviate_allocation(recommendation, recommendation.entry.entry_id)


def test_decisions_are_immutable_once_recorded(clock: ManualClock) -> None:
    engine = _engine(clock)
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))

    decision = engine.confirm_allocation(engine.recommend())

    with pytest.raises(FrozenInstanceError):
        decision.outcome = ArbitrationOutcome.DEVIATION  # type: ignore[misc]


def test_rank_history_ignores_decisions_interleaved_in_the_trail(clock: ManualClock) -> None:
    engine = Engine(
        survival_model=MapSurvivalModel({13: 0.8, 12: 0.7}),
        clock=clock,
        wait_horizon=timedelta(hours=24),
    )
    sick = _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # severity 13, survival 0.8 → top
    long_waiter = _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # severity 12, survival 0.7
    engine.snapshot("initial")
    recommendation = engine.recommend()
    # clinician deviates the bed to the long-waiter; the sick patient stays behind
    long_waiter_entry = next(
        e.entry_id for e in recommendation.queue if e.patient_id == long_waiter
    )
    engine.deviate_allocation(recommendation, long_waiter_entry)
    engine.snapshot("post-allocation")

    sick_history = engine.patient_rank_history(sick)
    waiter_history = engine.patient_rank_history(long_waiter)

    assert [(s.snapshot_id, rank) for s, rank in sick_history] == [(1, 1), (3, 1)]
    assert [(s.snapshot_id, rank) for s, rank in waiter_history] == [(1, 2)]


def test_recommendation_reasoning_carries_tie_break_explanation(clock: ManualClock) -> None:
    engine = Engine(
        survival_model=MapSurvivalModel({13: 0.7, 12: 0.7}),
        clock=clock,
        wait_horizon=timedelta(hours=24),
    )
    _register(engine, Sofa(2, 2, 2, 2, 2, 2))  # severity 12
    clock.advance(timedelta(hours=7))
    _register(engine, Sofa(3, 3, 2, 2, 2, 1))  # severity 13

    reasoning = engine.recommend().reasoning

    assert "tie-break: higher severity" in reasoning