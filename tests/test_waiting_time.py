from collections.abc import Callable
from datetime import timedelta

import pytest

from caregrid import Engine, EntryView, ManualClock, Sofa


def _ids(engine: Engine) -> list[str]:
    return [e.patient_id for e in engine.current_queue().entries]


def test_waiting_time_starts_at_zero(
    engine: Engine, patient_sofa: Sofa, entry_view: Callable[[Engine, str], EntryView]
) -> None:
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    view = entry_view(engine, entry_id)

    assert view.waiting_time == timedelta(0)
    assert view.waiting_factor == pytest.approx(0.0)


def test_waiting_time_accrues_with_the_clock(
    engine: Engine,
    clock: ManualClock,
    patient_sofa: Sofa,
    entry_view: Callable[[Engine, str], EntryView],
) -> None:
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)
    engine.current_queue()

    clock.advance(timedelta(hours=2))

    view = entry_view(engine, entry_id)
    assert view.waiting_time == timedelta(hours=2)


def test_new_queue_entry_resets_waiting_time(
    engine: Engine,
    clock: ManualClock,
    patient_sofa: Sofa,
    entry_view: Callable[[Engine, str], EntryView],
) -> None:
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    first = engine.open_entry(patient_id)
    clock.advance(timedelta(hours=6))
    engine.current_queue()
    engine.close_entry(first)

    second = engine.open_entry(patient_id)
    view = entry_view(engine, second)

    assert view.waiting_time == timedelta(0)


def test_waiting_factor_is_saturating_quadratic(
    engine_factory: Callable[..., Engine],
    clock: ManualClock,
    patient_sofa: Sofa,
    entry_view: Callable[[Engine, str], EntryView],
) -> None:
    engine = engine_factory(wait_horizon=timedelta(hours=24), clock=clock)
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)
    engine.current_queue()

    clock.advance(timedelta(hours=12))
    assert entry_view(engine, entry_id).waiting_factor == pytest.approx((12 / 24) ** 2)

    clock.advance(timedelta(hours=12))
    assert entry_view(engine, entry_id).waiting_factor == pytest.approx(1.0)

    clock.advance(timedelta(hours=48))
    assert entry_view(engine, entry_id).waiting_factor == pytest.approx(1.0)


def test_equal_clinical_patients_preserve_creation_order_on_tie(
    engine_factory: Callable[..., Engine], clock: ManualClock, patient_sofa: Sofa
) -> None:
    engine = engine_factory(wait_horizon=timedelta(hours=24), clock=clock)
    patient_a = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    patient_b = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    engine.open_entry(patient_a)
    engine.open_entry(patient_b)

    assert _ids(engine) == [patient_a, patient_b]

    clock.advance(timedelta(hours=24))

    assert _ids(engine) == [patient_a, patient_b]


def test_waiting_time_can_overturn_a_near_equal_ranking(
    engine_factory: Callable[..., Engine], clock: ManualClock, patient_sofa: Sofa
) -> None:
    engine = engine_factory(wait_horizon=timedelta(hours=24), clock=clock)
    patient_a = engine.register_patient(
        sofa=Sofa(3, 1, 2, 2, 2, 1), age=60, comorbidities=()
    )
    engine.open_entry(patient_a)

    clock.advance(timedelta(hours=6))
    patient_b = engine.register_patient(sofa=patient_sofa, age=60, comorbidities=())
    engine.open_entry(patient_b)

    assert _ids(engine) == [patient_b, patient_a]

    clock.advance(timedelta(hours=18))

    assert _ids(engine) == [patient_a, patient_b]


def test_new_arrival_reranks_before_the_next_query(
    engine: Engine, patient_sofa: Sofa
) -> None:
    patient_a = engine.register_patient(
        sofa=Sofa(1, 1, 1, 1, 1, 1), age=40, comorbidities=()
    )
    engine.open_entry(patient_a)
    assert _ids(engine) == [patient_a]

    patient_b = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    engine.open_entry(patient_b)

    assert _ids(engine) == [patient_b, patient_a]


def test_scores_are_internally_consistent(
    engine: Engine,
    clock: ManualClock,
    patient_sofa: Sofa,
    entry_view: Callable[[Engine, str], EntryView],
) -> None:
    patient_id = engine.register_patient(sofa=patient_sofa, age=64, comorbidities=())
    entry_id = engine.open_entry(patient_id)

    clock.advance(timedelta(hours=3))

    view = entry_view(engine, entry_id)
    profile = view.profile
    expected = (
        profile.severity * view.severity_factor
        + profile.survival * view.survival_factor
        + profile.waiting * view.waiting_factor
    )
    assert view.score == pytest.approx(expected)
    assert view.waiting_time == timedelta(hours=3)