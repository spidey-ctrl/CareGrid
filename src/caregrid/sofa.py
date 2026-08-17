from dataclasses import dataclass


@dataclass(frozen=True)
class Sofa:
    """The six organ-system components of the SOFA score, each 0-4. Higher is sicker."""

    respiration: int
    coagulation: int
    liver: int
    cardiovascular: int
    central_nervous: int
    renal: int

    def severity(self) -> int:
        return (
            self.respiration
            + self.coagulation
            + self.liver
            + self.cardiovascular
            + self.central_nervous
            + self.renal
        )