import pytest
from fastapi.testclient import TestClient

from caregrid import Engine, RankingSnapshot
from caregrid.scenario import demo_engine
from caregrid.web import create_dashboard_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_dashboard_app(demo_engine()))


def test_state_returns_live_queue_sorted_by_score_with_badge(
    client: TestClient,
) -> None:
    state = client.get("/api/state").json()

    scores = [e["score"] for e in state["queue"]]
    assert scores == sorted(scores, reverse=True)
    assert state["profile"]["name"] == "Severity-dominant"
    assert state["profile"]["severity"] == pytest.approx(0.5)
    assert state["wait_horizon_hours"] == 24.0
    assert state["as_of"].endswith("+00:00")


def test_state_rows_carry_the_full_factor_breakdown(client: TestClient) -> None:
    state = client.get("/api/state").json()

    for entry in state["queue"]:
        assert set(entry) >= {
            "entry_id",
            "patient_id",
            "rank",
            "score",
            "severity_factor",
            "survival_factor",
            "waiting_factor",
            "waiting_minutes",
            "survival_probability",
            "survival_attribution",
            "movement",
        }
        assert isinstance(entry["survival_attribution"], dict)
        assert entry["tie_break_reason"] is None or isinstance(
            entry["tie_break_reason"], str
        )


def test_movement_indicator_compares_live_rank_to_last_snapshot(
    client: TestClient,
) -> None:
    state = client.get("/api/state").json()

    movement = {e["patient_id"]: e["movement"] for e in state["queue"]}
    assert movement["patient-1"] == "unchanged"  # wait-exhausted top holds at the live view
    assert movement["patient-3"] == "up"  # the longer waiter of the near-tie pair climbs
    assert movement["patient-4"] == "down"


def test_state_event_feed_covers_every_arrival_rerank_and_allocation(
    client: TestClient,
) -> None:
    state = client.get("/api/state").json()

    kinds = [e["kind"] for e in state["events"]]
    assert kinds.count("arrival") == 5
    assert kinds.count("re-rank") == 5  # every snapshot, including the removal and allocation
    assert kinds.count("removal") == 2  # the mid-run discharge plus the allocation
    assert "bed-freed" in kinds
    assert "allocation" in kinds


def test_trail_lists_every_record_in_order(client: TestClient) -> None:
    trail = client.get("/api/trail").json()

    assert [(t["id"], t["type"]) for t in trail] == [
        (1, "snapshot"),
        (2, "snapshot"),
        (3, "snapshot"),
        (4, "snapshot"),
        (5, "decision"),
        (6, "snapshot"),
    ]


def test_replaying_a_snapshot_record_renders_the_exact_past_queue(
    client: TestClient,
) -> None:
    record = client.get("/api/record/3").json()

    assert record["type"] == "snapshot"
    assert record["trigger"] == "tip-arrival"
    assert record["profile"]["name"] == "Severity-dominant"
    assert [e["patient_id"] for e in record["queue"]] == [
        "patient-5",
        "patient-1",
        "patient-4",
        "patient-3",
    ]


def test_replaying_the_decision_record_renders_the_queue_at_allocation(
    client: TestClient,
) -> None:
    record = client.get("/api/record/5").json()

    assert record["type"] == "decision"
    assert record["outcome"] == "confirmed"
    assert record["allocated"] == "patient-5"
    assert record["recommended"] == "patient-5"
    assert record["reasoning"].startswith("patient-5 is ranked #1")
    assert record["queue"][0]["patient_id"] == "patient-5"


def test_snapshot_endpoint_returns_the_exact_stored_record(
    client: TestClient,
) -> None:
    body = client.get("/api/snapshot/1").json()

    assert body["trigger"] == "ward-opened"
    assert [e["patient_id"] for e in body["queue"]] == ["patient-1", "patient-2"]
    assert body["wait_horizon_hours"] == 24.0


def test_unknown_record_snapshot_and_patient_are_404(client: TestClient) -> None:
    assert client.get("/api/record/99").status_code == 404
    assert client.get("/api/snapshot/99").status_code == 404
    assert client.get("/api/patient/no-such-patient/history").status_code == 404


def test_patient_history_reports_ranks_across_snapshots(client: TestClient) -> None:
    history = client.get("/api/patient/patient-1/history").json()

    assert [(h["snapshot_id"], h["rank"]) for h in history] == [
        (1, 1),
        (2, 1),
        (3, 2),
        (4, 2),
        (6, 1),
    ]


def test_demo_scenario_is_loaded_with_a_near_tie_and_tipping_arrival(
    client: TestClient,
) -> None:
    record = client.get("/api/record/3").json()

    assert record["queue"][0]["patient_id"] == "patient-5"  # tipping arrival tops the list
    above, below = record["queue"][2], record["queue"][3]
    assert above["patient_id"] == "patient-4"
    assert below["patient_id"] == "patient-3"
    assert above["score"] == pytest.approx(below["score"], abs=0.005)
    assert above["tie_break_reason"] is not None
    assert "higher severity" in above["tie_break_reason"]


def test_dashboard_is_read_only(client: TestClient) -> None:
    """The web layer exposes no mutation endpoints — it only reads engine outputs."""
    app = create_dashboard_app(demo_engine())
    methods = {
        method
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert not (methods & {"POST", "PUT", "PATCH", "DELETE"})


def test_demo_engine_is_deterministic() -> None:
    first, second = demo_engine(), demo_engine()

    def queues(engine: Engine) -> list[tuple[int, list[str]]]:
        return [
            (s.snapshot_id if isinstance(s, RankingSnapshot) else s.decision_id,
             [e.patient_id for e in (s.entries if isinstance(s, RankingSnapshot) else s.queue)])
            for s in engine.trail()
        ]

    assert queues(first) == queues(second)
    assert [e.patient_id for e in first.current_queue().entries] == [
        e.patient_id for e in second.current_queue().entries
    ]