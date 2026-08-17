from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        ...


@dataclass
class ManualClock:
    """A controllable clock so time-dependent engine behaviour is deterministic in tests."""

    _now: datetime

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now = self._now + delta