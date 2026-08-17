"""Read-only web dashboard for the CareGrid domain engine.

A thin consumer of the engine's queries — the current ranked queue, Ranking
Snapshots, Arbitration Decisions, patient rank history, and the event stream.
It performs no decision logic of its own: every value served here is read from
engine outputs. The frontend is a Vite/React app built into ``frontend/dist``
and served as static files beside the JSON API.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from starlette.responses import Response

from .engine import (
    ArbitrationDecision,
    Engine,
    EntryView,
    Event,
    RankingSnapshot,
    TrailRecord,
)
from .profile import WeightProfile
from .scenario import demo_engine

FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _profile_json(profile: WeightProfile) -> dict[str, float | str]:
    return {
        "name": profile.name,
        "severity": profile.severity,
        "survival": profile.survival,
        "waiting": profile.waiting,
    }


def _entry_json(
    entry: EntryView, rank: int, movement: str | None = None
) -> dict[str, object]:
    return {
        "entry_id": entry.entry_id,
        "patient_id": entry.patient_id,
        "rank": rank,
        "score": round(entry.score, 4),
        "severity_factor": round(entry.severity_factor, 4),
        "survival_factor": round(entry.survival_factor, 4),
        "waiting_factor": round(entry.waiting_factor, 4),
        "waiting_minutes": int(entry.waiting_time.total_seconds() / 60),
        "survival_probability": round(entry.survival_probability, 4),
        "survival_attribution": {
            key: round(value, 4) for key, value in entry.survival_attribution.items()
        },
        "tie_break_reason": entry.tie_break_reason,
        "movement": movement,
    }


def _queue_json(entries: list[EntryView]) -> list[dict[str, object]]:
    return [_entry_json(entry, rank) for rank, entry in enumerate(entries, start=1)]


def _event_json(event: Event) -> dict[str, str | int]:
    return {
        "id": event.id,
        "occurred_at": event.occurred_at.isoformat(timespec="seconds"),
        "kind": event.kind.value,
        "detail": event.detail,
    }


def _movement_by_entry(engine: Engine) -> dict[str, str]:
    """Rank movement of each live entry against the most recent snapshot.

    Derived purely from engine reads: the live queue's order versus the last
    snapshot's order. ``new`` marks entries that were not present to be ranked
    before.
    """
    previous: dict[str, int] = {}
    for record in engine.trail():
        if isinstance(record, RankingSnapshot):
            previous = {e.patient_id: rank for rank, e in enumerate(record.entries, 1)}
    movement: dict[str, str] = {}
    for rank, entry in enumerate(engine.current_queue().entries, start=1):
        prior_rank = previous.get(entry.patient_id)
        if prior_rank is None:
            movement[entry.entry_id] = "new"
        elif rank < prior_rank:
            movement[entry.entry_id] = "up"
        elif rank > prior_rank:
            movement[entry.entry_id] = "down"
        else:
            movement[entry.entry_id] = "unchanged"
    return movement


def _record_by_id(engine: Engine, record_id: int) -> TrailRecord | None:
    for record in engine.trail():
        if (
            isinstance(record, RankingSnapshot)
            and record.snapshot_id == record_id
        ) or (
            isinstance(record, ArbitrationDecision)
            and record.decision_id == record_id
        ):
            return record
    return None


def _record_summary(record: TrailRecord) -> dict[str, object]:
    if isinstance(record, RankingSnapshot):
        return {
            "id": record.snapshot_id,
            "type": "snapshot",
            "occurred_at": record.captured_at.isoformat(timespec="seconds"),
            "label": f"re-rank — {record.trigger}",
        }
    return {
        "id": record.decision_id,
        "type": "decision",
        "occurred_at": record.recorded_at.isoformat(timespec="seconds"),
        "label": f"{record.outcome.value} — {record.allocated.patient_id} allocated",
    }


def _record_json(record: TrailRecord) -> dict[str, object]:
    if isinstance(record, RankingSnapshot):
        summary = _record_summary(record)
        queue = list(record.entries)
        summary["trigger"] = record.trigger
    else:
        summary = _record_summary(record)
        queue = list(record.queue)
        summary["outcome"] = record.outcome.value
        summary["reasoning"] = record.reasoning
        summary["note"] = record.note
        summary["recommended"] = record.recommended.patient_id
        summary["allocated"] = record.allocated.patient_id
    summary["profile"] = _profile_json(record.profile)
    summary["wait_horizon_hours"] = record.wait_horizon.total_seconds() / 3600
    summary["queue"] = _queue_json(queue)
    return summary


def _state_json(engine: Engine) -> dict[str, object]:
    queue = engine.current_queue()
    movement = _movement_by_entry(engine)
    return {
        "as_of": engine.now().isoformat(timespec="seconds"),
        "profile": _profile_json(queue.profile),
        "wait_horizon_hours": queue.wait_horizon.total_seconds() / 3600,
        "queue": [
            _entry_json(entry, rank, movement.get(entry.entry_id))
            for rank, entry in enumerate(queue.entries, start=1)
        ],
        "events": [_event_json(event) for event in engine.events()],
        "trail": [_record_summary(record) for record in engine.trail()],
    }


def create_dashboard_app(engine: Engine) -> FastAPI:
    """FastAPI app serving the dashboard's read-only JSON API and the React build."""

    app = FastAPI(title="CareGrid Dashboard", docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/api/state")
    def state() -> dict[str, object]:
        return _state_json(engine)

    @app.get("/api/trail")
    def trail() -> list[dict[str, object]]:
        return [_record_summary(record) for record in engine.trail()]

    @app.get("/api/events")
    def events() -> list[dict[str, str | int]]:
        return [_event_json(event) for event in engine.events()]

    @app.get("/api/record/{record_id}")
    def record(record_id: int) -> dict[str, object]:
        trailed = _record_by_id(engine, record_id)
        if trailed is None:
            raise HTTPException(status_code=404, detail=f"no trail record #{record_id}")
        return _record_json(trailed)

    @app.get("/api/snapshot/{snapshot_id}")
    def snapshot(snapshot_id: int) -> dict[str, object]:
        try:
            return _record_json(engine.snapshot_at(snapshot_id))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/patient/{patient_id}/history")
    def patient_history(patient_id: str) -> list[dict[str, object]]:
        try:
            history = engine.patient_rank_history(patient_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [
            {
                "snapshot_id": snapshot.snapshot_id,
                "rank": rank,
                "occurred_at": snapshot.captured_at.isoformat(timespec="seconds"),
                "trigger": snapshot.trigger,
            }
            for snapshot, rank in history
        ]

    @app.get("/", include_in_schema=False)
    def index() -> Response:
        index_path = FRONTEND_DIST / "index.html"
        if not index_path.is_file():
            return PlainTextResponse(
                "The dashboard UI is not built. Run `npm --prefix frontend install && "
                "npm --prefix frontend run build`, then reload.",
                status_code=503,
            )
        return FileResponse(index_path)

    @app.get("/assets/{path:path}", include_in_schema=False)
    def assets(path: str) -> FileResponse:
        asset_root = (FRONTEND_DIST / "assets").resolve()
        target = (asset_root / path).resolve()
        if asset_root not in target.parents or not target.is_file():
            raise HTTPException(status_code=404, detail=f"no asset '{path}'")
        return FileResponse(target)

    return app