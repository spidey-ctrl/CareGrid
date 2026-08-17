from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Mapping, Protocol

from .clock import Clock
from .profile import SEVERITY_DOMINANT, WeightProfile
from .sofa import Sofa
from .survival import SurvivalModel, SurvivalPrediction

PatientId = str
EntryId = str

DEFAULT_WAIT_HORIZON = timedelta(hours=24)


def _fmt_duration(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    return f"{hours:g}h"


@dataclass(frozen=True)
class Patient:
    id: PatientId
    sofa: Sofa
    age: int
    comorbidities: tuple[str, ...]
    survival: SurvivalPrediction

    def severity_factor(self) -> float:
        return self.sofa.severity() / 24.0

    def survival_factor(self) -> float:
        return self.survival.probability


@dataclass(frozen=True)
class EntryView:
    entry_id: EntryId
    patient_id: PatientId
    score: float
    severity_factor: float
    survival_factor: float
    waiting_factor: float
    survival_probability: float
    survival_attribution: Mapping[str, float]
    waiting_time: timedelta
    created_at: datetime
    profile: WeightProfile
    tie_break_reason: str | None = None


@dataclass(frozen=True)
class QueueView:
    profile: WeightProfile
    wait_horizon: timedelta
    entries: tuple[EntryView, ...]


@dataclass(frozen=True)
class RankingSnapshot:
    """An immutable, append-only audit record of one re-rank's full outcome."""

    snapshot_id: int
    captured_at: datetime
    trigger: str
    profile: WeightProfile
    wait_horizon: timedelta
    entries: tuple[EntryView, ...]


@dataclass(frozen=True)
class Recommendation:
    """The engine's suggested allocation for a freed bed, carrying its full reasoning."""

    trigger: str
    entry: EntryView
    queue: tuple[EntryView, ...]
    reasoning: str


class ArbitrationOutcome(Enum):
    CONFIRMED = "confirmed"
    DEVIATION = "deviation"


@dataclass(frozen=True)
class ArbitrationDecision:
    """The record of one bed assignment, appended to the same trail as the snapshots.

    Always carries what was recommended and what the clinician actually allocated, so a
    deliberate deviation is visible at a glance and every assignment is self-contained.
    """

    decision_id: int
    recorded_at: datetime
    trigger: str
    outcome: ArbitrationOutcome
    profile: WeightProfile
    wait_horizon: timedelta
    queue: tuple[EntryView, ...]
    recommended: EntryView
    allocated: EntryView
    reasoning: str
    note: str | None = None


TrailRecord = RankingSnapshot | ArbitrationDecision


class EventKind(Enum):
    """The kinds of state change the engine stream reports to its readers.

    The event stream is a read-side view of queue operations — arrivals, removals,
    profile switches, re-ranks, freed beds, and allocations — so consumers like the
    dashboard can show what moved the queue without re-deriving it from the trail.
    """

    ARRIVAL = "arrival"
    REMOVAL = "removal"
    PROFILE_CHANGE = "profile-change"
    RERANK = "re-rank"
    BED_FREED = "bed-freed"
    ALLOCATION = "allocation"


@dataclass(frozen=True)
class Event:
    """One immutable record in the engine's event stream."""

    id: int
    occurred_at: datetime
    kind: EventKind
    detail: str


def _weight_breakdown(profile: WeightProfile) -> str:
    parts = (
        round(profile.severity * 100),
        round(profile.survival * 100),
        round(profile.waiting * 100),
    )
    return "/".join(str(p) for p in parts)


def _recommendation_reasoning(view: EntryView, wait_horizon: timedelta) -> str:
    """The human-readable 'why this entry' that rides on every freed-bed recommendation."""
    reason = f"; {view.tie_break_reason}" if view.tie_break_reason else ""
    return (
        f"{view.patient_id} is ranked #1 with priority score {view.score:.3f} — "
        f"severity {view.severity_factor:.3f}, survival {view.survival_factor:.3f}, "
        f"waiting {_fmt_duration(view.waiting_time)} → {view.waiting_factor:.3f} — "
        f"under {view.profile.name} ({_weight_breakdown(view.profile)}), "
        f"wait horizon {_fmt_duration(wait_horizon)}{reason}"
    )


def _fmt_deviation_suffix(allocated: EntryView, recommended: EntryView) -> str:
    if allocated.entry_id == recommended.entry_id:
        return ""
    return f" (deviated from recommended {recommended.patient_id})"


class UnknownPatient(ValueError):
    pass


class UnknownEntry(ValueError):
    pass


class UnknownSnapshot(ValueError):
    pass


class UnknownDecision(ValueError):
    pass


class EmptyQueue(ValueError):
    pass


class StaleRecommendation(ValueError):
    pass


class InvalidDeviation(ValueError):
    pass


@dataclass
class _QueueEntry:
    id: EntryId
    patient_id: PatientId
    created_at: datetime


class Engine:
    """The domain engine — the single public door through which all behaviour is exercised."""

    def __init__(
        self,
        *,
        survival_model: SurvivalModel,
        clock: Clock,
        profile: WeightProfile | None = None,
        wait_horizon: timedelta | None = None,
    ):
        self._survival_model = survival_model
        self._clock = clock
        self._profile = profile if profile is not None else SEVERITY_DOMINANT
        self._wait_horizon = wait_horizon if wait_horizon is not None else DEFAULT_WAIT_HORIZON
        self._patients: dict[PatientId, Patient] = {}
        self._entries: dict[EntryId, _QueueEntry] = {}
        self._trail: tuple[TrailRecord, ...] = ()
        self._events: tuple[Event, ...] = ()
        self._next_patient = 1
        self._next_entry = 1
        self._next_trail = 1
        self._next_event = 1

    def register_patient(
        self, *, sofa: Sofa, age: int, comorbidities: tuple[str, ...]
    ) -> PatientId:
        patient_id = f"patient-{self._next_patient}"
        self._next_patient += 1
        survival = self._survival_model.predict(sofa, age, comorbidities)
        self._patients[patient_id] = Patient(
            id=patient_id, sofa=sofa, age=age, comorbidities=comorbidities, survival=survival
        )
        return patient_id

    def open_entry(self, patient_id: PatientId) -> EntryId:
        if patient_id not in self._patients:
            raise UnknownPatient(patient_id)
        entry_id = f"entry-{self._next_entry}"
        self._next_entry += 1
        self._entries[entry_id] = _QueueEntry(
            id=entry_id, patient_id=patient_id, created_at=self._clock.now()
        )
        self._record_event(
            EventKind.ARRIVAL, f"{patient_id} arrived; queue entry {entry_id} opened"
        )
        return entry_id

    def set_profile(self, profile: WeightProfile) -> None:
        """Switch the active profile; every already-ranked Queue Entry rescored under it."""
        self._profile = profile
        self._record_event(
            EventKind.PROFILE_CHANGE, f"weight profile switched to {profile.name}"
        )

    def close_entry(self, entry_id: EntryId) -> None:
        if entry_id not in self._entries:
            raise UnknownEntry(entry_id)
        patient_id = self._entries[entry_id].patient_id
        del self._entries[entry_id]
        self._record_event(
            EventKind.REMOVAL, f"{patient_id} removed; queue entry {entry_id} closed"
        )

    def current_queue(self) -> QueueView:
        return QueueView(
            profile=self._profile,
            wait_horizon=self._wait_horizon,
            entries=tuple(self._rank(self._clock.now())),
        )

    def _rank(self, now: datetime) -> list[EntryView]:
        views = [self._entry_view(e, now) for e in self._entries.values()]
        views.sort(
            key=lambda v: (
                -round(v.score, 2),
                -v.severity_factor,
                -v.survival_factor,
                -v.waiting_factor,
                v.created_at,
            )
        )
        self._annotate_ties(views)
        return views

    def snapshot(self, trigger: str) -> RankingSnapshot:
        """Re-rank under the current profile and append an immutable record to the trail."""
        now = self._clock.now()
        entries = tuple(self._rank(now))
        record = RankingSnapshot(
            snapshot_id=self._next_trail,
            captured_at=now,
            trigger=trigger,
            profile=self._profile,
            wait_horizon=self._wait_horizon,
            entries=entries,
        )
        self._trail = (*self._trail, record)
        self._next_trail += 1
        self._record_event(
            EventKind.RERANK,
            f"re-ranked {len(entries)} entries — trigger: {trigger}",
        )
        return record

    def recommend(self, trigger: str = "bed-freed") -> Recommendation:
        """Produce the recommendation for the current top-ranked entry, without allocating."""
        now = self._clock.now()
        queue = tuple(self._rank(now))
        if not queue:
            raise EmptyQueue("cannot recommend a freed bed — the queue is empty")
        top = queue[0]
        self._record_event(
            EventKind.BED_FREED,
            f"bed freed — {top.patient_id} recommended top candidate",
        )
        return Recommendation(
            trigger=trigger,
            entry=top,
            queue=queue,
            reasoning=_recommendation_reasoning(top, self._wait_horizon),
        )

    def confirm_allocation(
        self, recommendation: Recommendation, *, note: str | None = None
    ) -> ArbitrationDecision:
        """Allocate the recommended entry to the freed bed and record the confirmation."""
        return self._allocate(
            recommendation, allocated_entry_id=recommendation.entry.entry_id, note=note
        )

    def deviate_allocation(
        self,
        recommendation: Recommendation,
        allocated_entry_id: EntryId,
        *,
        note: str | None = None,
    ) -> ArbitrationDecision:
        """Allocate a lower-ranked entry at the clinician's deliberate choice (ADR-0002)."""
        if allocated_entry_id == recommendation.entry.entry_id:
            raise InvalidDeviation(
                f"{recommendation.entry.entry_id} is the recommended entry — "
                "allocation follows the recommendation, so use confirm_allocation"
            )
        return self._allocate(
            recommendation, allocated_entry_id=allocated_entry_id, note=note
        )

    def _allocate(
        self, recommendation: Recommendation, allocated_entry_id: EntryId, *, note: str | None
    ) -> ArbitrationDecision:
        """Append the allocation decision to the trail, then let the allocated entry leave.

        The clinician's choice always wins (ADR-0002): a confirmation allocates the
        recommended entry, a deviation allocates the lower-ranked entry the clinician
        consciously picked instead.
        """
        now = self._clock.now()
        queue = tuple(self._rank(now))
        recommended_view = next(
            (v for v in queue if v.entry_id == recommendation.entry.entry_id), None
        )
        if recommended_view is None:
            raise StaleRecommendation(
                f"{recommendation.entry.entry_id} is no longer in the queue — "
                "request a fresh recommendation"
            )
        allocated_view = next((v for v in queue if v.entry_id == allocated_entry_id), None)
        if allocated_view is None:
            raise UnknownEntry(allocated_entry_id)

        if allocated_view.entry_id == recommended_view.entry_id:
            outcome = ArbitrationOutcome.CONFIRMED
        else:
            ranks = {
                v.entry_id: rank for rank, v in enumerate(queue, start=1)
            }
            if ranks[allocated_view.entry_id] <= ranks[recommended_view.entry_id]:
                raise InvalidDeviation(
                    f"{allocated_view.entry_id} (rank #{ranks[allocated_view.entry_id]}) "
                    f"is not below the recommended {recommended_view.entry_id} "
                    f"(rank #{ranks[recommended_view.entry_id]})"
                )
            outcome = ArbitrationOutcome.DEVIATION

        decision = ArbitrationDecision(
            decision_id=self._next_trail,
            recorded_at=now,
            trigger=recommendation.trigger,
            outcome=outcome,
            profile=self._profile,
            wait_horizon=self._wait_horizon,
            queue=queue,
            recommended=recommended_view,
            allocated=allocated_view,
            reasoning=recommendation.reasoning,
            note=note,
        )
        self._trail = (*self._trail, decision)
        self._next_trail += 1
        deviation = _fmt_deviation_suffix(allocated_view, recommended_view)
        self._record_event(
            EventKind.ALLOCATION,
            f"{outcome.value}: bed allocated to {allocated_view.patient_id}{deviation}",
        )
        self.close_entry(allocated_view.entry_id)
        return decision

    def now(self) -> datetime:
        """The engine's current instant — a read query for consumers that show 'as of' time."""
        return self._clock.now()

    def trail(self) -> tuple[TrailRecord, ...]:
        """The append-only audit trail, in creation order."""
        return self._trail

    def events(self) -> tuple[Event, ...]:
        """The append-only event stream, in occurrence order (spec query)."""
        return self._events

    def _record_event(self, kind: EventKind, detail: str) -> None:
        self._events = (*self._events, Event(
            id=self._next_event, occurred_at=self._clock.now(), kind=kind, detail=detail
        ))
        self._next_event += 1

    def snapshot_at(self, snapshot_id: int) -> RankingSnapshot:
        """The stored snapshot for a past re-rank — a direct read, no re-running of commands."""
        for record in self._trail:
            if isinstance(record, RankingSnapshot) and record.snapshot_id == snapshot_id:
                return record
        raise UnknownSnapshot(snapshot_id)

    def decision_at(self, decision_id: int) -> ArbitrationDecision:
        """The stored Arbitration Decision for a past bed assignment, without replaying."""
        for record in self._trail:
            if isinstance(record, ArbitrationDecision) and record.decision_id == decision_id:
                return record
        raise UnknownDecision(decision_id)

    def patient_rank_history(
        self, patient_id: PatientId
    ) -> tuple[tuple[RankingSnapshot, int], ...]:
        """Every snapshot the Patient was ranked in, with their 1-based rank at the time."""
        if patient_id not in self._patients:
            raise UnknownPatient(patient_id)
        history: list[tuple[RankingSnapshot, int]] = []
        for record in self._trail:
            if not isinstance(record, RankingSnapshot):
                continue
            for rank, entry in enumerate(record.entries, start=1):
                if entry.patient_id == patient_id:
                    history.append((record, rank))
                    break
        return tuple(history)

    def _annotate_ties(self, views: list[EntryView]) -> None:
        """Walk each group of equal-rounded scores and record how each member beat the next.

        Entries only a few hundredths apart in score never share a group, so the
        cascade only ever explains genuinely near-equal orderings.
        """
        i = 0
        while i < len(views):
            j = i + 1
            while j < len(views) and round(views[j].score, 2) == round(views[i].score, 2):
                j += 1
            for k in range(i, j - 1):
                reason = self._tie_break_reason(views[k], views[k + 1])
                if reason is not None:
                    views[k] = replace(views[k], tie_break_reason=reason)
            i = j

    @staticmethod
    def _tie_break_reason(above: EntryView, below: EntryView) -> str | None:
        """The cascade stage that ranks `above` ahead of `below`, or None if fully tied."""
        if above.severity_factor != below.severity_factor:
            return (
                "tie-break: higher severity "
                f"({above.severity_factor:.3f} vs {below.severity_factor:.3f})"
            )
        if above.survival_factor != below.survival_factor:
            return (
                "tie-break: higher survival "
                f"({above.survival_factor:.3f} vs {below.survival_factor:.3f})"
            )
        if above.waiting_factor != below.waiting_factor:
            return (
                "tie-break: longer wait "
                f"({_fmt_duration(above.waiting_time)} vs {_fmt_duration(below.waiting_time)})"
            )
        if above.created_at != below.created_at:
            return (
                "tie-break: earlier entry "
                f"({above.created_at.isoformat(timespec='seconds')})"
            )
        return None

    def _waiting_factor(self, waiting_time: timedelta) -> float:
        ratio = waiting_time / self._wait_horizon
        return min(1.0, ratio * ratio)

    def _entry_view(self, entry: _QueueEntry, now: datetime) -> EntryView:
        patient = self._patients[entry.patient_id]
        severity_factor = patient.severity_factor()
        survival_factor = patient.survival_factor()
        waiting_time = now - entry.created_at
        waiting_factor = self._waiting_factor(waiting_time)
        score = (
            self._profile.severity * severity_factor
            + self._profile.survival * survival_factor
            + self._profile.waiting * waiting_factor
        )
        return EntryView(
            entry_id=entry.id,
            patient_id=patient.id,
            score=score,
            severity_factor=severity_factor,
            survival_factor=survival_factor,
            waiting_factor=waiting_factor,
            survival_probability=patient.survival.probability,
            survival_attribution=patient.survival.attribution,
            waiting_time=waiting_time,
            created_at=entry.created_at,
            profile=self._profile,
        )