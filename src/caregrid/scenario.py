"""Scenario seeding for the web dashboard — a stand-in for the Simulation Run (ticket 09).

`demo_engine()` builds a deterministic, deliberately loaded ICU-style queue for the
dashboard to consume: an exhausted long-waiter, a near-tie that breaks on the
severity stage, a mid-severity patient who overtakes the long-waiter at the live
view, and a tipping arrival. Every number is hand-engineered under the
Severity-dominant profile with constant survival 0.7, so the scenario reads by
inspection and needs no trained model.
"""

from datetime import datetime, timedelta, timezone

from .clock import ManualClock
from .engine import Engine
from .profile import SEVERITY_DOMINANT
from .sofa import Sofa
from .survival import SurvivalModel, SurvivalPrediction

T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


class _DemoSurvivalModel:
    """Deterministic stand-in kept for tests that must not train the real model.

    Since ticket 08 the demonstration paths inject the validated trained model where
    available; this fake remains only where a demonstration is not being run — unit and
    dashboard tests that exercise the engine with a fixed, hand-controllable survival.
    """

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        return SurvivalPrediction(
            probability=0.7,
            attribution={
                "respiration": round(-0.04 * sofa.respiration, 3),
                "cardiovascular": round(-0.03 * sofa.cardiovascular, 3),
                "renal": round(-0.02 * sofa.renal, 3),
                "central_nervous": round(-0.02 * sofa.central_nervous, 3),
                "age": round(-0.05 * age / 80, 3),
            },
        )


def demo_engine(model: SurvivalModel | None = None) -> Engine:
    """A deliberately loaded ICU-style queue for the dashboard, under a survival model.

    ``model`` is the validated trained survival model on demonstration paths; with no
    model passed (tests) the constant hand-controllable stand-in is used instead.
    """
    clock = ManualClock(T0)
    engine = Engine(
        survival_model=model if model is not None else _DemoSurvivalModel(),
        clock=clock,
        profile=SEVERITY_DOMINANT,
    )

    def admit(sofa: Sofa, age: int, at: datetime) -> str:
        clock.set(at)
        patient_id = engine.register_patient(sofa=sofa, age=age, comorbidities=())
        engine.open_entry(patient_id)
        return patient_id

    admit(Sofa(3, 1, 2, 2, 1, 1), 74, T0 - timedelta(hours=36))  # patient-1: exhausted long-waiter
    admit(Sofa(2, 2, 2, 2, 2, 2), 50, T0 - timedelta(hours=20))  # patient-2: mid-severity drifter
    clock.set(T0 - timedelta(hours=18))
    engine.snapshot("ward-opened")
    admit(Sofa(2, 2, 2, 2, 2, 1), 62, T0 - timedelta(hours=12))  # patient-3: near-tie, lower severity
    admit(Sofa(3, 2, 2, 2, 2, 2), 47, T0 - timedelta(hours=6))  # patient-4: near-tie, higher severity
    tip = admit(Sofa(4, 3, 3, 4, 3, 3), 41, T0)  # patient-5: tipping arrival (SOFA 20)
    engine.snapshot("tip-arrival")
    engine.snapshot("bed-freed")
    recommendation = engine.recommend()
    engine.confirm_allocation(recommendation)
    engine.snapshot("post-allocation")

    clock.advance(timedelta(hours=3))  # waiting-time drift so the live view shows rank movement
    return engine