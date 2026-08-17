"""Command-line entry point for CareGrid.

`caregrid demo` prints the ranked ICU queue for a ward — the default demo
ward, or a ward you specify. A thin consumer of the domain engine; it holds
no decision logic of its own.
"""

import argparse
from datetime import datetime, timezone
from typing import Sequence

from .clock import ManualClock
from .engine import Engine, EntryView
from .sofa import Sofa
from .survival import SurvivalModel, SurvivalPrediction

DEFAULT_WARD: Sequence[tuple[Sofa, int, tuple[str, ...]]] = (
    (Sofa(3, 1, 2, 2, 3, 1), 64, ("diabetes",)),
    (Sofa(4, 4, 3, 4, 4, 3), 58, ("COPD", "heart failure")),
    (Sofa(1, 1, 1, 1, 1, 1), 45, ()),
    (Sofa(3, 2, 3, 2, 3, 2), 77, ("chronic renal disease",)),
)


class PlaceholderSurvivalModel:
    """Deterministic stand-in for the trained survival model, which arrives in ticket 08.

    Survival falls as severity rises; the engine is agnostic to what sits behind
    the SurvivalModel adapter seam.
    """

    def predict(self, sofa: Sofa, age: int, comorbidities: tuple[str, ...]) -> SurvivalPrediction:
        p = max(0.05, min(0.95, 0.95 - sofa.severity() * 0.03 - age * 0.002))
        return SurvivalPrediction(
            probability=round(p, 3),
            attribution={"sofa_total": round(0.1 - sofa.severity() * 0.01, 3), "age": -0.05},
        )


def _parse_patient(spec: str) -> tuple[Sofa, int, tuple[str, ...]]:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) < 7:
        raise SystemExit(f"invalid patient '{spec}' — need six SOFA organ components, an age, then optional comorbidities")
    try:
        organs = [int(part) for part in parts[:6]]
        age = int(parts[6])
    except ValueError:
        raise SystemExit(f"invalid patient '{spec}' — SOFA components and age must be integers")
    if any(o < 0 or o > 4 for o in organs):
        raise SystemExit(f"invalid patient '{spec}' — each SOFA organ component is 0-4")
    if age < 0 or age > 120:
        raise SystemExit(f"invalid patient '{spec}' — age must be 0-120")
    comorbidities = tuple(c for c in parts[7].split(";") if c) if len(parts) > 7 else ()
    return Sofa(*organs), age, comorbidities


def _format(rank: int, view: EntryView) -> str:
    return (
        f"{rank:<5}{view.patient_id:<11}{view.score:<7.3f}{view.severity_factor:<7.3f}"
        f"{view.survival_factor:<7.3f}{view.waiting_factor:<7.3f}{view.survival_probability:<7.3f} "
        f"{view.profile.name}"
    )


def _print_queue(views: Sequence[EntryView]) -> None:
    header = (
        f"{'rank':<5}{'patient':<11}{'score':<7}{'sev_f':<7}{'surv_f':<7}"
        f"{'wait_f':<7}{'p_surv':<7} profile"
    )
    print(header)
    for rank, view in enumerate(views, start=1):
        print(_format(rank, view))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="caregrid",
        description="ICU bed-arbitration decision-support engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="print the ranked ICU queue for a ward")
    demo.add_argument(
        "patients",
        nargs="*",
        metavar="PATIENT",
        help=(
            "custom patient spec: six SOFA organ components (0-4), age, optional "
            "comorbidities; e.g. '3,1,2,2,3,1,64,diabetes;COPD'. Defaults to a demo ward."
        ),
    )
    args = parser.parse_args(argv)

    if args.command == "demo":
        ward = [_parse_patient(p) for p in args.patients] if args.patients else DEFAULT_WARD
        engine = Engine(
            survival_model=PlaceholderSurvivalModel(),
            clock=ManualClock(datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)),
        )
        for sofa, age, comorbidities in ward:
            patient_id = engine.register_patient(sofa=sofa, age=age, comorbidities=comorbidities)
            engine.open_entry(patient_id)
        _print_queue(engine.current_queue().entries)
        return 0

    parser.error(f"unknown command '{args.command}'")
    return 2
