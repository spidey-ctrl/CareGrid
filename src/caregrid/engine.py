from dataclasses import dataclass, replace
from datetime import datetime, timedelta
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


class UnknownPatient(ValueError):
    pass


class UnknownEntry(ValueError):
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
        self._next_patient = 1
        self._next_entry = 1

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
        return entry_id

    def set_profile(self, profile: WeightProfile) -> None:
        """Switch the active profile; every already-ranked Queue Entry rescored under it."""
        self._profile = profile

    def close_entry(self, entry_id: EntryId) -> None:
        if entry_id not in self._entries:
            raise UnknownEntry(entry_id)
        del self._entries[entry_id]

    def current_queue(self) -> QueueView:
        now = self._clock.now()
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
        return QueueView(profile=self._profile, wait_horizon=self._wait_horizon, entries=tuple(views))

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