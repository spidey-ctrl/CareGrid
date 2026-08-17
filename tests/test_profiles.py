from collections.abc import Callable
from datetime import timedelta

from conftest import T0
import pytest

from caregrid import (
    BALANCED,
    Engine,
    ManualClock,
    SEVERITY_DOMINANT,
    SEVERITY_HEAVY,
    Sofa,
    SurvivalPrediction,
    WeightProfile,
)

PRESET_SPLITS = {
    SEVERITY_DOMINANT: (0.5, 0.3, 0.2),
    BALANCED: (0.4, 0.3, 0.3),
    SEVERITY_HEAVY: (0.6, 0.25, 0.15),
}


@pytest.mark.parametrize(
    ("profile", "split"),
    list(PRESET_SPLITS.items()),
    ids=lambda p: p.name if isinstance(p, WeightProfile) else str(p),
)
def test_presets_have_exact_splits(profile: WeightProfile, split: tuple[float, float, float]) -> None:
    assert (profile.severity, profile.survival, profile.waiting) == split


class BySeverityModel:
    def __init__(self, probabilities: dict[int, float]) -> None:
        self.probabilities = probabilities

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        return SurvivalPrediction(
            probability=self.probabilities[sofa.severity()], attribution={}
        )


def _register(engine: Engine, sofa: Sofa, age: int = 60) -> str:
    patient_id = engine.register_patient(sofa=sofa, age=age, comorbidities=())
    return engine.open_entry(patient_id)


def _entry_ids(engine: Engine) -> list[str]:
    return [e.entry_id for e in engine.current_queue().entries]


def test_switching_profile_rescores_every_already_ranked_entry(
    engine_factory: Callable[..., Engine],
) -> None:
    engine = engine_factory()
    _register(engine, Sofa(3, 1, 2, 2, 3, 1))
    baseline = engine.current_queue().entries[0]

    engine.set_profile(BALANCED)
    rescored = engine.current_queue().entries[0]

    assert rescored.entry_id == baseline.entry_id
    assert rescored.score != baseline.score
    assert (rescored.severity_factor, rescored.survival_factor, rescored.waiting_factor) == (
        baseline.severity_factor,
        baseline.survival_factor,
        baseline.waiting_factor,
    )


def test_active_profile_rides_along_on_every_query(
    engine_factory: Callable[..., Engine],
) -> None:
    engine = engine_factory(profile=BALANCED)
    _register(engine, Sofa(3, 1, 2, 2, 3, 1))

    assert engine.current_queue().profile == BALANCED
    assert engine.current_queue().entries[0].profile == BALANCED


def test_switching_profile_back_and_forth_restores_scores(
    engine_factory: Callable[..., Engine],
) -> None:
    engine = engine_factory()
    _register(engine, Sofa(3, 1, 2, 2, 3, 1))
    original = engine.current_queue().entries[0].score

    engine.set_profile(SEVERITY_HEAVY)
    engine.set_profile(SEVERITY_DOMINANT)

    assert engine.current_queue().entries[0].score == original


def test_severity_dominant_ranks_most_severe_highest(
    engine_factory: Callable[..., Engine],
) -> None:
    engine = engine_factory(probability=0.7)
    for sofa in (Sofa(1, 1, 1, 1, 1, 1), Sofa(3, 2, 3, 2, 3, 2), Sofa(4, 4, 4, 4, 4, 4)):
        _register(engine, sofa)

    ordered = engine.current_queue().entries

    assert [e.severity_factor for e in ordered] == sorted(
        (e.severity_factor for e in ordered), reverse=True
    )


def test_profiles_produce_orderings_matching_their_intent() -> None:
    """The same queue flips order when the profile shifts which factor dominates.

    A sick-but-just-arrived patient and an exhausted long-waiter compete: severity
    pressure says the sick patient, waiting says the long-waiter. Severity-heavy
    should favour the sick patient; Severity-dominant and Balanced the long-waiter.
    """
    clock = ManualClock(T0)
    engine = Engine(
        survival_model=BySeverityModel({16: 0.6, 6: 0.7}),
        clock=clock,
        wait_horizon=timedelta(hours=24),
    )
    long_waiter = _register(engine, Sofa(1, 1, 1, 1, 1, 1))  # severity 6, created T0
    clock.advance(timedelta(hours=24))  # snapshot moment
    sick = _register(engine, Sofa(3, 3, 3, 3, 2, 2))  # severity 16, waits 0h

    long_waiter_first = [long_waiter, sick]
    sick_first = [sick, long_waiter]

    engine.set_profile(SEVERITY_DOMINANT)
    assert _entry_ids(engine) == long_waiter_first
    engine.set_profile(BALANCED)
    assert _entry_ids(engine) == long_waiter_first
    engine.set_profile(SEVERITY_HEAVY)
    assert _entry_ids(engine) == sick_first