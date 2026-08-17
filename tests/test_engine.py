from datetime import datetime, timedelta, timezone

import pytest

from caregrid import (
    Engine,
    EntryView,
    ManualClock,
    Sofa,
    SurvivalPrediction,
)


class FakeSurvivalModel:
    """Deterministic stand-in for the trained survival model, injected at the adapter seam."""

    def __init__(self, probability: float = 0.7) -> None:
        self.probability = probability

    def predict(
        self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]
    ) -> SurvivalPrediction:
        return SurvivalPrediction(
            probability=self.probability,
            attribution={"sofa_total": 0.1, "age": 0.05},
        )


def make_engine(probability: float = 0.7) -> Engine:
    return Engine(
        survival_model=FakeSurvivalModel(probability),
        clock=ManualClock(datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)),
    )


def sofa() -> Sofa:
    return Sofa(respiration=3, coagulation=1, liver=2, cardiovascular=2, central_nervous=3, renal=1)


def entry_view(engine: Engine, entry_id: str) -> EntryView:
    return next(e for e in engine.current_queue().entries if e.entry_id == entry_id)


def test_register_patient_returns_stable_identity() -> None:
    engine = make_engine()

    patient_id = engine.register_patient(sofa=sofa(), age=64, comorbidities=("diabetes",))

    assert patient_id is not None
    assert engine.open_entry(patient_id) is not None


def test_open_entry_for_unknown_patient_is_rejected() -> None:
    engine = make_engine()

    with pytest.raises(ValueError):
        engine.open_entry("no-such-patient")


def test_closed_entry_leaves_the_queue() -> None:
    engine = make_engine()
    patient_id = engine.register_patient(sofa=sofa(), age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    engine.close_entry(entry_id)

    queue = engine.current_queue()
    assert all(e.entry_id != entry_id for e in queue.entries)


def test_closing_unknown_entry_is_rejected() -> None:
    engine = make_engine()

    with pytest.raises(ValueError):
        engine.close_entry("no-such-entry")


def test_priority_score_is_weighted_sum_of_severity_and_survival_factors() -> None:
    engine = make_engine()
    patient_id = engine.register_patient(sofa=sofa(), age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    view = entry_view(engine, entry_id)

    assert view.severity_factor == pytest.approx(12 / 24)
    assert view.survival_factor == pytest.approx(0.7)
    assert view.waiting_factor == pytest.approx(0.0)
    assert view.score == pytest.approx(
        0.5 * (12 / 24) + 0.3 * 0.7 + 0.2 * 0.0
    )


def test_entry_view_carries_breakdown_profile_and_shap_attribution() -> None:
    engine = make_engine()
    patient_id = engine.register_patient(sofa=sofa(), age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    view = entry_view(engine, entry_id)

    assert view.patient_id == patient_id
    assert view.survival_probability == pytest.approx(0.7)
    assert view.survival_attribution == {"sofa_total": 0.1, "age": 0.05}
    assert view.profile.name == "Severity-dominant"
    assert view.profile.severity == pytest.approx(0.5)
    assert view.profile.survival == pytest.approx(0.3)
    assert view.profile.waiting == pytest.approx(0.2)
    assert engine.current_queue().profile == view.profile


def test_queue_is_ranked_highest_score_first() -> None:
    engine = make_engine(probability=0.7)
    patient_a = engine.register_patient(sofa=sofa(), age=64, comorbidities=())
    patient_b = engine.register_patient(
        sofa=Sofa(1, 1, 1, 1, 1, 1), age=40, comorbidities=()
    )
    engine.open_entry(patient_b)
    engine.open_entry(patient_a)

    queue = engine.current_queue()
    scores = [e.score for e in queue.entries]

    assert scores == sorted(scores, reverse=True)
    assert [e.patient_id for e in queue.entries] == [patient_a, patient_b]


def test_survival_model_is_injected_at_the_adapter_seam() -> None:
    engine = make_engine(probability=0.9)
    patient_id = engine.register_patient(sofa=sofa(), age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    view = entry_view(engine, entry_id)

    assert view.survival_factor == pytest.approx(0.9)
    assert view.score == pytest.approx(0.5 * (12 / 24) + 0.3 * 0.9)


def test_controllable_clock_is_wired_and_scores_stay_inert_when_time_moves() -> None:
    clock = ManualClock(datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc))
    engine = Engine(survival_model=FakeSurvivalModel(), clock=clock)
    patient_id = engine.register_patient(sofa=sofa(), age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)
    created_at = entry_view(engine, entry_id).created_at
    score_before = entry_view(engine, entry_id).score

    clock.advance(timedelta(hours=2))

    view = entry_view(engine, entry_id)
    assert view.created_at == created_at
    assert view.score == pytest.approx(score_before)
    assert view.waiting_factor == pytest.approx(0.0)