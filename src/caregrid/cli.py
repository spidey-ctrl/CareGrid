"""Command-line entry point for CareGrid.

`caregrid demo` prints the ranked ICU queue for a ward — the default demo
ward, patients given on the command line, or a ward loaded from a CSV
(with optional staggered arrivals and clock advance to exercise waiting
time). A thin consumer of the domain engine; it holds no decision logic.
"""

import argparse
import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

from .clock import ManualClock
from .engine import Engine, EntryView
from .profile import PRESETS, WeightProfile
from .sofa import Sofa
from .survival import SurvivalModel, SurvivalPrediction

DEFAULT_WARD: Sequence[tuple[Sofa, int, tuple[str, ...]]] = (
    (Sofa(3, 1, 2, 2, 3, 1), 64, ("diabetes",)),
    (Sofa(4, 4, 3, 4, 4, 3), 58, ("COPD", "heart failure")),
    (Sofa(1, 1, 1, 1, 1, 1), 45, ()),
    (Sofa(3, 2, 3, 2, 3, 2), 77, ("chronic renal disease",)),
)

_ORGAN_COLUMNS = (
    "respiration",
    "coagulation",
    "liver",
    "cardiovascular",
    "central_nervous",
    "renal",
)
_SOFA_TOTAL_CANDIDATES = {"sofa", "sofa total", "total sofa", "sofa_total", "total_sofa"}
_AGE_CANDIDATES = {"age", "age_years"}
_COMORBIDITY_CANDIDATES = {"comorbidity", "comorbidities"}
_CREATED_CANDIDATES = {"arrival_date", "arrival time", "arrival", "created_at", "created"}


@dataclass(frozen=True)
class _RawPatient:
    sofa: Sofa
    age: int
    comorbidities: tuple[str, ...]
    created_at: datetime | None


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


def _base_time() -> datetime:
    return datetime(2026, 1, 1, 8, 0, tzinfo=timezone.utc)


def _parse_patient(spec: str) -> _RawPatient:
    parts = [p.strip() for p in spec.split(",")]
    if len(parts) < 7:
        raise SystemExit(
            f"invalid patient '{spec}' — need six SOFA organ components, an age, then optional comorbidities"
        )
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
    return _RawPatient(sofa=Sofa(*organs), age=age, comorbidities=comorbidities, created_at=None)


def _pick(headers: list[str], candidates: set[str]) -> str | None:
    lowered = [h.strip().lower() for h in headers]
    for i, name in enumerate(lowered):
        if name in candidates:
            return headers[i]
    return None


def _to_int(value: Any) -> int | None:
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _parse_created(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        return datetime.combine(date.fromisoformat(text), datetime.min.time()).replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return None


def _load_csv(path: str, limit: int | None) -> list[_RawPatient]:
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        raise SystemExit(f"'{path}' has no data rows")
    headers = rows[0]

    organ_cols: dict[str, str] = {}
    for organ in _ORGAN_COLUMNS:
        col = _pick(headers, {organ, organ.replace("_", " ")})
        if col is not None:
            organ_cols[organ] = col
    has_all_organs = len(organ_cols) == len(_ORGAN_COLUMNS)

    sofa_col = None if has_all_organs else _pick(headers, _SOFA_TOTAL_CANDIDATES)
    age_col = _pick(headers, _AGE_CANDIDATES)
    comorbidity_col = _pick(headers, _COMORBIDITY_CANDIDATES)
    created_col = _pick(headers, _CREATED_CANDIDATES)

    if not has_all_organs and sofa_col is None:
        raise SystemExit(
            f"'{path}' has no SOFA data — need six organ components "
            "(respiration, coagulation, liver, cardiovascular, central_nervous, renal) "
            "or a SOFA total column"
        )
    if age_col is None:
        raise SystemExit(f"'{path}' has no age column")

    loaded: list[_RawPatient] = []
    skip = 0
    for row in rows[1:]:
        if limit is not None and len(loaded) >= limit:
            break
        values = dict(zip(headers, row))
        age = _to_int(values.get(age_col)) if age_col else None
        if age is None or not (0 <= age <= 120):
            skip += 1
            continue
        if has_all_organs:
            organs: list[int] = []
            usable = True
            for organ in _ORGAN_COLUMNS:
                value = _to_int(values.get(organ_cols[organ]))
                if value is None or not (0 <= value <= 4):
                    usable = False
                    break
                organs.append(value)
            if not usable:
                skip += 1
                continue
            sofa = Sofa.from_total(sum(organs))
        else:
            sofa_total = _to_int(values.get(sofa_col)) if sofa_col else None
            if sofa_total is None or not (0 <= sofa_total <= 24):
                skip += 1
                continue
            sofa = Sofa.from_total(sofa_total)
        comorbidities: tuple[str, ...] = ()
        if comorbidity_col:
            comorbidities = tuple(
                c.strip()
                for c in (values.get(comorbidity_col) or "").split(";")
                if c.strip()
            )
        created_at = _parse_created(values.get(created_col)) if created_col else None
        loaded.append(
            _RawPatient(
                sofa=sofa, age=age, comorbidities=comorbidities, created_at=created_at
            )
        )
    return loaded


def _apply_stagger(
    patients: Sequence[_RawPatient], base: datetime, stagger_hours: int
) -> list[_RawPatient]:
    result: list[_RawPatient] = []
    for i, patient in enumerate(patients):
        created = patient.created_at
        if created is None and stagger_hours:
            created = base - timedelta(hours=i * stagger_hours)
        result.append(
            _RawPatient(
                sofa=patient.sofa,
                age=patient.age,
                comorbidities=patient.comorbidities,
                created_at=created,
            )
        )
    return result


def _register_ward(engine: Engine, patients: Sequence[_RawPatient], snapshot: datetime) -> None:
    """Open queue entries for each patient at their stated creation time, in input order.

    Patient ids therefore follow the input rows, with each entry's recorded creation
    time matching the staggered arrival. The clock finishes at `snapshot`, the moment
    the first queue view is taken.
    """
    clock = cast(ManualClock, engine._clock)
    for patient in patients:
        created = patient.created_at or clock.now()
        clock.advance(created - clock.now())
        patient_id = engine.register_patient(
            sofa=patient.sofa, age=patient.age, comorbidities=patient.comorbidities
        )
        engine.open_entry(patient_id)
    clock.advance(snapshot - clock.now())


def _fmt_wait(waiting_time: timedelta) -> str:
    total_hours = waiting_time.total_seconds() / 3600
    days = int(total_hours // 24)
    hours = int(total_hours % 24)
    return f"{days}d{hours:02d}h" if days else f"{hours}h"


def _format(rank: int, view: EntryView) -> str:
    return (
        f"{rank:<5}{view.patient_id:<11}{view.score:<7.3f}{view.severity_factor:<7.3f}"
        f"{view.survival_factor:<7.3f}{view.waiting_factor:<7.3f}{_fmt_wait(view.waiting_time):<10}"
        f"{view.survival_probability:<7.3f} {view.profile.name}"
    )


def _print_queue(views: Sequence[EntryView]) -> None:
    header = (
        f"{'rank':<5}{'patient':<11}{'score':<7}{'sev_f':<7}{'surv_f':<7}"
        f"{'wait_f':<7}{'waiting':<10}{'p_surv':<7} profile"
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
    demo.add_argument(
        "--csv",
        metavar="PATH",
        help=(
            "load a ward from CSV instead; uses six SOFA organ columns, or a SOFA "
            "total column; Age is required; optional comorbidity/comorbidities and "
            "arrival_date/created_at columns"
        ),
    )
    demo.add_argument("--limit", type=int, metavar="N", help="only load the first N CSV rows")
    demo.add_argument(
        "--stagger-hours",
        type=int,
        metavar="H",
        help="for CSV loads without arrival dates, space each arrival H hours apart",
    )
    demo.add_argument(
        "--advance-hours",
        type=float,
        metavar="H",
        help="after ranking, advance the clock H hours and print the re-ranked queue",
    )
    demo.add_argument(
        "--profile",
        choices=[p.name for p in PRESETS],
        default=PRESETS[0].name,
        help=f"weight profile to score under (default: {PRESETS[0].name})",
    )
    args = parser.parse_args(argv)

    if args.command == "demo":
        base = _base_time()
        model = PlaceholderSurvivalModel()
        profile = next(p for p in PRESETS if p.name == args.profile)
        engine = Engine(survival_model=model, clock=ManualClock(base), profile=profile)

        if args.csv:
            if args.patients:
                parser.error("cannot combine positional PATIENT specs with --csv")
            loaded = _load_csv(args.csv, args.limit)
            if not loaded:
                print("no usable rows loaded — check the SOFA/Age columns")
                return 1
            patients = _apply_stagger(loaded, base, args.stagger_hours or 0)
            print(f"loaded {len(loaded)} patients from {args.csv}\n")
        else:
            if args.stagger_hours:
                parser.error("--stagger-hours only applies to --csv loads")
            raw = [_parse_patient(p) for p in args.patients] if args.patients else [
                _RawPatient(sofa=s, age=a, comorbidities=c, created_at=None)
                for s, a, c in DEFAULT_WARD
            ]
            patients = raw

        _register_ward(engine, patients, snapshot=base)
        _print_queue(engine.current_queue().entries)

        if args.advance_hours:
            print(f"\nafter {args.advance_hours:g} hours:\n")
            cast(ManualClock, engine._clock).advance(timedelta(hours=args.advance_hours))  # noqa: SLF001
            _print_queue(engine.current_queue().entries)
        return 0

    parser.error(f"unknown command '{args.command}'")
    return 2