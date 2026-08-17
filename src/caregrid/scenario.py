"""The Simulation Run (ticket 09) — the end-to-end demonstration scenario.

A Simulation Run is a self-contained, deterministic ICU-style queue that deliberately
loads the edge cases the arbitration logic must survive — an exhausted long-waiter, a
near-tie that resolves on the severity stage of the Tie-Break Cascade, and a tipping
arrival that overtakes the wait-exhausted top — then plays arrivals, a removal, and a
freed bed through the domain engine under a chosen Weight Profile and yields the
Ranking Snapshot trail a reviewer can replay end-to-end.

Every number is hand-engineered under the default Severity-dominant profile with the
constant-survival stand-in (p = 0.7), so the near-tie resolves and the tipping arrival
overtakes by inspection there — that is the reference survival the tests and the
dashboard run against; the validated trained model is plugged in on demonstration paths
(the CLI, the dashboard), which is also what keeps the ticket 8 validation gate in the
loop. Rankings under the real model differ numerically but the scenario structure — who
arrives when, what is removed, and which edge cases are staged — is identical.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .clock import ManualClock
from .engine import Engine
from .profile import SEVERITY_DOMINANT, WeightProfile
from .sofa import Sofa
from .survival import SurvivalModel, SurvivalPrediction

# The scenario's zero hour: every event below is scheduled relative to this instant.
T0 = datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)

# Snapshot trigger names, shared between the generator, the CLI, the dashboard, and the
# tests so a reviewer's replay narration and the code stay in lockstep.
WARD_OPENED = "ward-opened"
REMOVAL = "removal"
TIP_ARRIVAL = "tip-arrival"
BED_FREED = "bed-freed"
POST_ALLOCATION = "post-allocation"


@dataclass(frozen=True)
class _CastMember:
    """One character in the scenario, with everything the engine needs to admit them."""

    sofa: Sofa
    age: int


# The deliberately loaded cast. The long-waiter, the near-tie pair, and the tipping
# arrival are the three edge cases; the drifter is a mid-severity patient whose removal
# re-ranks the queue mid-scenario.
LONG_WAITER = _CastMember(Sofa(3, 1, 2, 2, 1, 1), 74)  # SOFA 10, waits past the 24h horizon
DRIFTER = _CastMember(Sofa(2, 2, 2, 2, 2, 2), 50)  # SOFA 12, removed before the free bed
TIE_LOWER = _CastMember(Sofa(2, 2, 2, 2, 2, 1), 62)  # SOFA 11, near-tie, lower severity
TIE_HIGHER = _CastMember(Sofa(3, 2, 2, 2, 2, 2), 47)  # SOFA 13, near-tie, higher severity
TIP = _CastMember(Sofa(4, 3, 3, 4, 3, 3), 41)  # SOFA 20, the tipping arrival


class _DemoSurvivalModel:
    """Deterministic stand-in kept for tests and the dashboard that must not train the model.

    Since ticket 08 the demonstration paths inject the validated trained model where
    available; this fake remains only where a demonstration is not being run — unit and
    dashboard tests that exercise the engine with a fixed, hand-controllable survival.
    The scenario's edge cases are engineered against this constant p = 0.7.
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


def run_simulation(
    *, profile: WeightProfile = SEVERITY_DOMINANT, model: SurvivalModel | None = None
) -> Engine:
    """Play the loaded scenario under ``profile`` and return the replayed engine.

    ``model`` is the validated trained survival model on demonstration paths; with no
    model passed (tests) the constant hand-controllable stand-in is used instead. The
    returned engine carries the full Ranking Snapshot trail plus the Arbitration
    Decision, so a reviewer can walk the whole story backwards and forwards.
    """
    clock = ManualClock(T0)
    engine = Engine(
        survival_model=model if model is not None else _DemoSurvivalModel(),
        clock=clock,
        profile=profile,
    )

    def admit(member: _CastMember, at: datetime) -> str:
        clock.set(at)
        patient_id = engine.register_patient(sofa=member.sofa, age=member.age, comorbidities=())
        return engine.open_entry(patient_id)

    hour = timedelta(hours=1)

    admit(LONG_WAITER, T0 - 36 * hour)  # patient-1: exhausted long-waiter
    drifter = admit(DRIFTER, T0 - 20 * hour)  # patient-2: mid-severity, removed later
    clock.set(T0 - 18 * hour)
    engine.snapshot(WARD_OPENED)  # the ward opens with the long-waiter in place

    admit(TIE_LOWER, T0 - 12 * hour)  # patient-3: near-tie, lower severity, longer waiter
    admit(TIE_HIGHER, T0 - 6 * hour)  # patient-4: near-tie, higher severity

    # A removal re-ranks the queue: the mid-severity patient is discharged before the
    # free bed arrives, so the arbitration moment sees the live post-removal ordering.
    clock.set(T0 - 4 * hour)
    engine.close_entry(drifter)
    engine.snapshot(REMOVAL)

    admit(TIP, T0)  # patient-5: the tipping arrival (SOFA 20) overtakes the long-waiter
    engine.snapshot(TIP_ARRIVAL)  # the near-tie pair resolves here on the severity stage

    engine.snapshot(BED_FREED)  # a bed frees up; the live queue is ranked
    engine.confirm_allocation(engine.recommend())  # the clinician confirms the top entry
    engine.snapshot(POST_ALLOCATION)

    clock.advance(3 * hour)  # waiting-time drift so the live view shows rank movement
    return engine


def demo_engine(model: SurvivalModel | None = None) -> Engine:
    """The dashboard's seeded live view — the Simulation Run under the default profile."""
    return run_simulation(profile=SEVERITY_DOMINANT, model=model)