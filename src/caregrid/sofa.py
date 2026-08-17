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

    @classmethod
    def from_total(cls, total: int) -> "Sofa":
        """Build a Sofa from a resolved SOFA total (0-24) using a balanced organ split.

        Used when a dataset provides only the total score, not the six components.
        The split is deterministic — components get the average, remainder spread
        across organs in order — so severity is preserved and equal totals score
        identically.
        """
        if total < 0 or total > 24:
            raise ValueError(f"SOFA total must be 0-24, got {total}")
        base, extra = divmod(total, 6)
        counts = [base + (1 if i < extra else 0) for i in range(6)]
        return cls(
            respiration=counts[0],
            coagulation=counts[1],
            liver=counts[2],
            cardiovascular=counts[3],
            central_nervous=counts[4],
            renal=counts[5],
        )