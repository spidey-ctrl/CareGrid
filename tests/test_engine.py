from collections.abc import Callable

import pytest

from caregrid import Engine, EntryView, Sofa


def test_register_patient_returns_stable_identity(
    engine: Engine, patient_sofa: Sofa
) -> None:
    patient_id = engine.register_patient(
        sofa=patient_sofa, age=64, comorbidities=("diabetes",)
    )

    assert patient_id is not None
    assert engine.open_entry(patient_id) is not None


def test_open_entry_for_unknown_patient_is_rejected(engine: Engine) -> None:
    with pytest.raises(ValueError):
        engine.open_entry("no-such-patient")


def test_closed_entry_leaves_the_queue(engine: Engine, patient_sofa: Sofa) -> None:
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    engine.close_entry(entry_id)

    queue = engine.current_queue()
    assert all(e.entry_id != entry_id for e in queue.entries)


def test_closing_unknown_entry_is_rejected(engine: Engine) -> None:
    with pytest.raises(ValueError):
        engine.close_entry("no-such-entry")


def test_priority_score_is_weighted_sum_of_severity_and_survival_factors(
    engine: Engine, patient_sofa: Sofa, entry_view: Callable[[Engine, str], EntryView]
) -> None:
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    view = entry_view(engine, entry_id)

    assert view.severity_factor == pytest.approx(12 / 24)
    assert view.survival_factor == pytest.approx(0.7)
    assert view.waiting_factor == pytest.approx(0.0)
    assert view.score == pytest.approx(0.5 * (12 / 24) + 0.3 * 0.7 + 0.2 * 0.0)


def test_entry_view_carries_breakdown_profile_and_shap_attribution(
    engine: Engine, patient_sofa: Sofa, entry_view: Callable[[Engine, str], EntryView]
) -> None:
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
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


def test_queue_is_ranked_highest_score_first(engine: Engine, patient_sofa: Sofa) -> None:
    patient_a = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    patient_b = engine.register_patient(
        sofa=Sofa(1, 1, 1, 1, 1, 1), age=40, comorbidities=()
    )
    engine.open_entry(patient_b)
    engine.open_entry(patient_a)

    queue = engine.current_queue()
    scores = [e.score for e in queue.entries]

    assert scores == sorted(scores, reverse=True)
    assert [e.patient_id for e in queue.entries] == [patient_a, patient_b]


def test_survival_model_is_injected_at_the_adapter_seam(
    engine_factory: Callable[..., Engine],
    patient_sofa: Sofa,
    entry_view: Callable[[Engine, str], EntryView],
) -> None:
    engine = engine_factory(probability=0.9)
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    view = entry_view(engine, entry_id)

    assert view.survival_factor == pytest.approx(0.9)
    assert view.score == pytest.approx(0.5 * (12 / 24) + 0.3 * 0.9)