"""Tests for the Simulation Run (ticket 09).

The run is the end-to-end demonstration: a deterministic ICU-style queue that
deliberately loads the edge cases — an exhausted long-waiter, a near-tie resolved on
the severity stage, and a tipping arrival — then plays arrivals, a removal, and a freed
bed through the engine under a chosen weight profile, yielding the snapshot trail a
reviewer can replay end to end. Tests assert on the run's outputs through the engine's
public reads (trail, snapshots, events, queues); they never inspect internals.
"""

from datetime import timedelta

import pytest

from conftest import T0

from caregrid import (
    BALANCED,
    PRESETS,
    ArbitrationDecision,
    Engine,
    RankingSnapshot,
    SEVERITY_DOMINANT,
    SEVERITY_HEAVY,
    Sofa,
    SurvivalPrediction,
    WeightProfile,
)
from caregrid.scenario import (
    BED_FREED,
    POST_ALLOCATION,
    REMOVAL,
    TIP_ARRIVAL,
    WARD_OPENED,
    demo_engine,
    run_simulation,
)

WAIT_HORIZON = timedelta(hours=24)


class ConstantSurvivalModel:
    """A deterministic survival stand-in, substituted at the adapter seam."""

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        return SurvivalPrediction(
            probability=0.7,
            attribution={"sofa_total": round(sofa.severity() / 24 - 0.5, 3)},
        )


def _snapshot(engine: Engine, trigger: str) -> RankingSnapshot:
    return next(
        record
        for record in engine.trail()
        if isinstance(record, RankingSnapshot) and record.trigger == trigger
    )


def _decision(engine: Engine) -> ArbitrationDecision:
    return next(
        record for record in engine.trail() if isinstance(record, ArbitrationDecision)
    )


def _signature(engine: Engine) -> list[tuple[int, str, list[str]]]:
    return [
        (
            record.snapshot_id
            if isinstance(record, RankingSnapshot)
            else record.decision_id,
            record.trigger if isinstance(record, RankingSnapshot) else record.outcome.value,
            [entry.patient_id for entry in record.entries]
            if isinstance(record, RankingSnapshot)
            else [entry.patient_id for entry in record.queue],
        )
        for record in engine.trail()
    ]


def test_scenario_is_deterministic_between_runs() -> None:
    first, second = run_simulation(), run_simulation()

    assert _signature(first) == _signature(second)
    assert [e.patient_id for e in first.current_queue().entries] == [
        e.patient_id for e in second.current_queue().entries
    ]
    assert [(e.id, e.kind.value) for e in first.events()] == [
        (e.id, e.kind.value) for e in second.events()
    ]


def test_scenario_loads_the_exhausted_long_waiter_capped_at_the_horizon() -> None:
    engine = run_simulation()
    tip = _snapshot(engine, TIP_ARRIVAL)
    long_waiter = next(entry for entry in tip.entries if entry.patient_id == "patient-1")

    assert long_waiter.waiting_time == timedelta(hours=36)
    assert long_waiter.waiting_time > WAIT_HORIZON
    assert long_waiter.waiting_factor == pytest.approx(1.0)  # wait-exhausted: capped


def test_scenario_loads_the_near_tie_resolved_on_the_severity_stage() -> None:
    engine = run_simulation(profile=SEVERITY_DOMINANT)
    tip = _snapshot(engine, TIP_ARRIVAL)
    above, below = tip.entries[2], tip.entries[3]

    assert (above.patient_id, below.patient_id) == ("patient-4", "patient-3")
    assert round(above.score, 2) == round(below.score, 2)  # near-equal after rounding
    assert above.tie_break_reason is not None
    assert "higher severity" in above.tie_break_reason


def test_scenario_tipping_arrival_overtakes_the_wait_exhausted_top() -> None:
    engine = run_simulation(profile=SEVERITY_DOMINANT)
    tip = _snapshot(engine, TIP_ARRIVAL)
    top, previous_top = tip.entries[0], tip.entries[1]

    assert top.patient_id == "patient-5"
    assert top.waiting_time == timedelta(0)  # arrived exactly at the tipping instant
    assert previous_top.patient_id == "patient-1"
    assert previous_top.severity_factor < top.severity_factor
    assert top.score > previous_top.score  # SOFA 20 out-ranks the wait-exhausted long-waiter


def test_scenario_plays_a_removal_that_reranks_the_queue() -> None:
    engine = run_simulation()
    opened = _snapshot(engine, WARD_OPENED)
    removal = _snapshot(engine, REMOVAL)
    opened_names = [e.patient_id for e in opened.entries]
    removal_names = [e.patient_id for e in removal.entries]

    assert "patient-2" in opened_names  # present when the ward opens
    assert "patient-2" not in removal_names  # gone by the removal re-rank
    assert "patient-2" not in [
        e.patient_id for e in _snapshot(engine, TIP_ARRIVAL).entries
    ]
    # two removal events: the mid-run discharge and the allocated patient leaving
    assert sum(1 for event in engine.events() if event.kind.value == "removal") == 2


def test_scenario_plays_the_freed_bed_and_records_the_decision() -> None:
    engine = run_simulation()
    decision = _decision(engine)

    assert decision.outcome.value == "confirmed"
    assert decision.allocated.patient_id == decision.recommended.patient_id == "patient-5"
    assert "patient-5" in [
        e.patient_id for e in _snapshot(engine, BED_FREED).entries
    ]
    assert "patient-5" not in [
        e.patient_id for e in _snapshot(engine, POST_ALLOCATION).entries
    ]
    assert "patient-5" not in [e.patient_id for e in engine.current_queue().entries]


def test_scenario_trail_replays_end_to_end() -> None:
    engine = run_simulation()
    trail = engine.trail()

    assert [(type(record).__name__, record.trigger) for record in trail] == [
        ("RankingSnapshot", WARD_OPENED),
        ("RankingSnapshot", REMOVAL),
        ("RankingSnapshot", TIP_ARRIVAL),
        ("RankingSnapshot", BED_FREED),
        ("ArbitrationDecision", "bed-freed"),
        ("RankingSnapshot", POST_ALLOCATION),
    ]
    # every record is retrievable as a direct read — no replay of the scenario
    for record in trail:
        if isinstance(record, RankingSnapshot):
            assert engine.snapshot_at(record.snapshot_id) is record
        else:
            assert engine.decision_at(record.decision_id) is record
    # patient-1's rank story: first at the open, overtaken by the tip, first again after
    assert [(s.snapshot_id, rank) for s, rank in engine.patient_rank_history("patient-1")] == [
        (1, 1),
        (2, 1),
        (3, 2),
        (4, 2),
        (6, 1),
    ]
    # the removed patient only ever appears in the opening snapshot
    assert [(s.snapshot_id, rank) for s, rank in engine.patient_rank_history("patient-2")] == [
        (1, 2)
    ]


def test_scenario_resulting_snapshots_are_never_reordered() -> None:
    engine = run_simulation()
    for record in engine.trail():
        if isinstance(record, RankingSnapshot):
            scores = [e.score for e in record.entries]
            assert scores == sorted(scores, reverse=True)


def test_scenario_waiting_time_drift_flips_the_near_tie_pair_live() -> None:
    engine = run_simulation()
    post = _snapshot(engine, POST_ALLOCATION)
    live = engine.current_queue().entries

    assert [e.patient_id for e in post.entries] == ["patient-1", "patient-4", "patient-3"]
    assert [e.patient_id for e in live] == ["patient-1", "patient-3", "patient-4"]
    # patient-3 waited longer, so once its wait factor outweighs the tie, it climbs
    assert live[1].waiting_time > live[2].waiting_time


@pytest.mark.parametrize(
    ("profile", "allocated", "post_allocation"),
    [
        (SEVERITY_DOMINANT, "patient-5", ["patient-1", "patient-4", "patient-3"]),
        (BALANCED, "patient-1", ["patient-5", "patient-3", "patient-4"]),
        (SEVERITY_HEAVY, "patient-5", ["patient-1", "patient-4", "patient-3"]),
    ],
)
def test_scenario_runs_under_every_weight_profile(
    profile: WeightProfile, allocated: str, post_allocation: list[str]
) -> None:
    engine = run_simulation(profile=profile)

    assert engine.current_queue().profile == profile
    assert [record.trigger for record in engine.trail()] == [
        WARD_OPENED,
        REMOVAL,
        TIP_ARRIVAL,
        BED_FREED,
        "bed-freed",
        POST_ALLOCATION,
    ]
    assert _decision(engine).allocated.patient_id == allocated
    assert [e.patient_id for e in _snapshot(engine, POST_ALLOCATION).entries] == post_allocation
    assert len(engine.current_queue().entries) == 3


def test_scenario_policy_sensitivity_is_visible_across_profiles() -> None:
    def live(engine: Engine) -> list[str]:
        return [e.patient_id for e in engine.current_queue().entries]

    dominant = live(run_simulation(profile=SEVERITY_DOMINANT))
    balanced = live(run_simulation(profile=BALANCED))
    heavy = live(run_simulation(profile=SEVERITY_HEAVY))

    # the identical queue ranks differently under each policy stance
    assert dominant == ["patient-1", "patient-3", "patient-4"]
    assert balanced == ["patient-5", "patient-3", "patient-4"]
    assert heavy == ["patient-1", "patient-4", "patient-3"]
    assert dominant != balanced
    assert dominant != heavy
    assert balanced != heavy
    # the loaded edge case itself shifts: the tipping arrival tops a severity-led queue,
    # while the wait-exhausted long-waiter holds under a waiting-weighted one
    assert _snapshot(run_simulation(profile=SEVERITY_DOMINANT), TIP_ARRIVAL).entries[0].patient_id == "patient-5"
    assert _snapshot(run_simulation(profile=BALANCED), TIP_ARRIVAL).entries[0].patient_id == "patient-1"


def test_demo_engine_is_the_default_profile_simulation_run() -> None:
    reference = run_simulation(profile=SEVERITY_DOMINANT)
    demo = demo_engine()

    assert _signature(demo) == _signature(reference)
    assert demo.current_queue().profile == SEVERITY_DOMINANT


def test_scenario_accepts_an_injected_survival_model() -> None:
    # Any SurvivalModel-ing adapter works; the run is fully model-parametric.
    engine = run_simulation(model=ConstantSurvivalModel())

    assert len(engine.trail()) == 6
    assert len(engine.current_queue().entries) == 3


def test_scenario_cli_refuses_when_the_validation_gate_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from caregrid import cli
    from caregrid.survival_model import ModelValidationError

    from pathlib import Path

    def _fail(*, seed: int = 0, x_csv: Path | None = None, y_csv: Path | None = None) -> None:
        raise ModelValidationError("AUC-ROC 0.58 < 0.60")

    monkeypatch.setattr(cli, "establish_survival_model", _fail)

    with pytest.raises(SystemExit) as excinfo:
        cli.main(["scenario"])
    assert excinfo.value.code == 1
    assert "demonstration blocked" in capsys.readouterr().err