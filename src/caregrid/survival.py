from dataclasses import dataclass
from typing import Mapping, Protocol

from .sofa import Sofa


@dataclass(frozen=True)
class SurvivalPrediction:
    probability: float
    attribution: Mapping[str, float]


class SurvivalModel(Protocol):
    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        ...