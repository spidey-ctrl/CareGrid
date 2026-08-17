from dataclasses import dataclass


@dataclass(frozen=True)
class WeightProfile:
    name: str
    severity: float
    survival: float
    waiting: float


SEVERITY_DOMINANT = WeightProfile(
    name="Severity-dominant", severity=0.5, survival=0.3, waiting=0.2
)