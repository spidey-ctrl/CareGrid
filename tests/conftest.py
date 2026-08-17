from collections.abc import Callable
from datetime import datetime, timedelta, timezone

import pytest

from caregrid import Engine, EntryView, ManualClock, Sofa, SurvivalPrediction, WeightProfile

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


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


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(T0)


@pytest.fixture
def engine(clock: ManualClock) -> Engine:
    return Engine(survival_model=FakeSurvivalModel(), clock=clock)


@pytest.fixture
def engine_factory() -> Callable[..., Engine]:
    def _make(
        probability: float = 0.7,
        *,
        wait_horizon: timedelta | None = None,
        clock: ManualClock | None = None,
        profile: WeightProfile | None = None,
    ) -> Engine:
        return Engine(
            survival_model=FakeSurvivalModel(probability),
            clock=clock if clock is not None else ManualClock(T0),
            wait_horizon=wait_horizon,
            profile=profile,
        )

    return _make


@pytest.fixture
def entry_view() -> Callable[[Engine, str], EntryView]:
    def _get(engine: Engine, entry_id: str) -> EntryView:
        return next(e for e in engine.current_queue().entries if e.entry_id == entry_id)

    return _get


@pytest.fixture
def patient_sofa() -> Sofa:
    return Sofa(3, 1, 2, 2, 3, 1)