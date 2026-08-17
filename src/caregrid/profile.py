from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class WeightProfile:
    name: str
    severity: float
    survival: float
    waiting: float


SEVERITY_DOMINANT: Final = WeightProfile(
    name="Severity-dominant", severity=0.5, survival=0.3, waiting=0.2
)

BALANCED: Final = WeightProfile(
    name="Balanced", severity=0.4, survival=0.3, waiting=0.3
)

SEVERITY_HEAVY: Final = WeightProfile(
    name="Severity-heavy", severity=0.6, survival=0.25, waiting=0.15
)

PRESETS: Final = (SEVERITY_DOMINANT, BALANCED, SEVERITY_HEAVY)