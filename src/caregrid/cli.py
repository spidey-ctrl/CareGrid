"""Command-line entry point for CareGrid.

`caregrid demo` prints the ranked ICU queue for a ward — the default demo
ward, patients given on the command line, or a ward loaded from a CSV
(with optional staggered arrivals and clock advance to exercise waiting
time). A thin consumer of the domain engine; it holds no decision logic.
"""

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, cast

from .clock import ManualClock
from .engine import (
    ArbitrationDecision,
    Engine,
    EntryView,
    RankingSnapshot,
    profile_weight_breakdown,
)
from .profile import PRESETS, WeightProfile
from .scenario import run_simulation
from .sofa import Sofa
from .survival import SurvivalModel
from .survival_model import ModelValidationError, establish_survival_model, SPLIT_SEED

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


def _survival_model() -> SurvivalModel:
    """The validated trained survival model — the demonstration gate.

    Ticket 08: every demonstration path (demo, allocate, serve) refuses to run on a
    model that fails the hold-out validation tolerance, per spec user story 50.
    """
    try:
        model, _ = establish_survival_model()
    except ModelValidationError as exc:
        print(f"demonstration blocked: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    return model


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


def _demand_ward(parser: argparse.ArgumentParser, args: argparse.Namespace) -> list[_RawPatient]:
    """Resolve the ward for a subcommand: CSV load or positional patient specs."""
    if getattr(args, "csv", None):
        if getattr(args, "patients", None):
            parser.error("cannot combine positional PATIENT specs with --csv")
        loaded = _load_csv(args.csv, getattr(args, "limit", None))
        if not loaded:
            print("no usable rows loaded — check the SOFA/Age columns")
            raise SystemExit(1)
        return _apply_stagger(loaded, _base_time(), getattr(args, "stagger_hours", 0) or 0)
    if getattr(args, "stagger_hours", 0):
        parser.error("--stagger-hours only applies to --csv loads")
    raw = (
        [_parse_patient(p) for p in args.patients]
        if getattr(args, "patients", None)
        else [
            _RawPatient(sofa=s, age=a, comorbidities=c, created_at=None)
            for s, a, c in DEFAULT_WARD
        ]
    )
    return raw


def _entry_spec(engine: Engine, spec: str) -> str:
    """Resolve a --deviate argument: an entry id, or the current entry of a named patient."""
    if spec in {e.entry_id for e in engine.current_queue().entries}:
        return spec
    matches = [e.entry_id for e in engine.current_queue().entries if e.patient_id == spec]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(f"'{spec}' is neither an entry id nor a queued patient id")
    raise SystemExit(f"'{spec}' matches multiple queued entries — pass an entry id")


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
        f"{'  ' + view.tie_break_reason if view.tie_break_reason else ''}"
    )


def _print_queue(views: Sequence[EntryView]) -> None:
    header = (
        f"{'rank':<5}{'patient':<11}{'score':<7}{'sev_f':<7}{'surv_f':<7}"
        f"{'wait_f':<7}{'waiting':<10}{'p_surv':<7} profile  tie-break"
    )
    print(header)
    for rank, view in enumerate(views, start=1):
        print(_format(rank, view))


def _fmt_deviation_suffix(allocated: EntryView, recommended: EntryView, verb: str) -> str:
    if allocated.entry_id == recommended.entry_id:
        return ""
    return f" {verb} {recommended.patient_id}"


def _profile_by_name(name: str) -> WeightProfile:
    return next(profile for profile in PRESETS if profile.name == name)


def _print_scenario_run(engine: Engine) -> None:
    """The full Simulation Run replay: every Ranking Snapshot's ordered queue and the decision."""
    profile = engine.current_queue().profile
    print(f"Simulation Run — {profile.name} ({profile_weight_breakdown(profile)})")
    print(
        "The loaded ICU queue: an exhausted long-waiter, a near-tie pair, and a tipping "
        "arrival, played through arrivals, a removal, and a freed bed."
    )
    print("\nAudit trail (replayable snapshots + the arbitration decision, in order):")
    for record in engine.trail():
        if isinstance(record, RankingSnapshot):
            print(
                f"\n  #{record.snapshot_id} {record.captured_at:%Y-%m-%d %H:%M} — "
                f"re-rank: {record.trigger}"
            )
            for rank, view in enumerate(record.entries, start=1):
                suffix = f"  {view.tie_break_reason}" if view.tie_break_reason else ""
                print(f"    {rank}. {view.patient_id:<10}{view.score:.3f}{suffix}")
        elif isinstance(record, ArbitrationDecision):
            deviation = _fmt_deviation_suffix(record.allocated, record.recommended, "deviated from")
            print(
                f"\n  #{record.decision_id} {record.recorded_at:%Y-%m-%d %H:%M} — "
                f"{record.outcome.value}: bed allocated to {record.allocated.patient_id}"
                f"{deviation}"
            )


def _print_scenario_block(profile: WeightProfile, engine: Engine) -> None:
    """A compact per-profile comparison line — same scenario, different policy stance."""
    print(f"\n{profile.name} ({profile_weight_breakdown(profile)})")
    for record in engine.trail():
        if isinstance(record, RankingSnapshot):
            names = ", ".join(view.patient_id for view in record.entries)
            print(f"  {record.trigger:<14} → {names}")
        elif isinstance(record, ArbitrationDecision):
            deviation = _fmt_deviation_suffix(record.allocated, record.recommended, ", deviated from")
            print(
                f"  {record.outcome.value:<14} → {record.allocated.patient_id} allocated"
                f"{deviation}"
            )


def _print_trail(engine: Engine) -> None:
    print("\nAudit trail:")
    for record in engine.trail():
        if isinstance(record, RankingSnapshot):
            top = record.entries[0] if record.entries else None
            summary = (
                f"  #{record.snapshot_id} {record.captured_at:%Y-%m-%d %H:%M} "
                f"{record.trigger:<12} snapshot: {len(record.entries)} entries"
            )
            if top:
                summary += f", top {top.patient_id} {top.score:.3f}"
            print(summary)
        elif isinstance(record, ArbitrationDecision):
            print(
                f"  #{record.decision_id} {record.recorded_at:%Y-%m-%d %H:%M} "
                f"{record.trigger:<12} {record.outcome.value}: {record.allocated.patient_id}"
                f"{_fmt_deviation_suffix(record.allocated, record.recommended, 'deviated from')}"
            )


def _add_ward_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "patients",
        nargs="*",
        metavar="PATIENT",
        help=(
            "custom patient spec: six SOFA organ components (0-4), age, optional "
            "comorbidities; e.g. '3,1,2,2,3,1,64,diabetes;COPD'. Defaults to a demo ward."
        ),
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help=(
            "load a ward from CSV instead; uses six SOFA organ columns, or a SOFA "
            "total column; Age is required; optional comorbidity/comorbidities and "
            "arrival_date/created_at columns"
        ),
    )
    parser.add_argument("--limit", type=int, metavar="N", help="only load the first N CSV rows")
    parser.add_argument(
        "--stagger-hours",
        type=int,
        metavar="H",
        help="for CSV loads without arrival dates, space each arrival H hours apart",
    )
    parser.add_argument(
        "--profile",
        choices=[p.name for p in PRESETS],
        default=PRESETS[0].name,
        help=f"weight profile to score under (default: {PRESETS[0].name})",
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="caregrid",
        description="ICU bed-arbitration decision-support engine",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    demo = sub.add_parser("demo", help="print the ranked ICU queue for a ward")
    _add_ward_args(demo)
    demo.add_argument(
        "--advance-hours",
        type=float,
        metavar="H",
        help="after ranking, advance the clock H hours and print the re-ranked queue",
    )
    allocate = sub.add_parser(
        "allocate",
        help="recommend the top entry for a freed bed and record the clinician's decision",
    )
    _add_ward_args(allocate)
    allocate.add_argument(
        "--deviate",
        metavar="ENTRY_OR_PATIENT",
        help=(
            "deviate to this lower-ranked entry instead of confirming the recommendation; "
            "accepts an entry id or a queued patient id"
        ),
    )
    allocate.add_argument(
        "--note",
        metavar="TEXT",
        help="free-text clinician note recorded on the decision",
    )
    serve = sub.add_parser(
        "serve",
        help="run the read-only web dashboard (React UI + JSON API)",
    )
    serve.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1)",
    )
    serve.add_argument(
        "--port",
        type=int,
        default=8000,
        help="port to listen on (default: 8000)",
    )
    _add_ward_args(serve)
    model_cmd = sub.add_parser(
        "model",
        help="train & validate the survival model, and gate demonstrations on it",
    )
    model_cmd.add_argument(
        "--seed",
        type=int,
        default=SPLIT_SEED,
        help=f"hold-out split seed (default: {SPLIT_SEED}, the recorded seed)",
    )
    scenario_cmd = sub.add_parser(
        "scenario",
        help=(
            "run the Simulation Run end-to-end and print its audit trail; "
            "gated on the survival model's validation"
        ),
    )
    scenario_cmd.add_argument(
        "--profile",
        choices=[p.name for p in PRESETS],
        default=None,
        help=(
            "weight profile to run the scenario under "
            "(default: all three, compared against the same queue)"
        ),
    )
    args = parser.parse_args(argv)

    if args.command == "model":
        from .survival_model import MODELS_DIR, report_to_dict

        print("training the CPU gradient-boosted survival model…", file=sys.stderr)
        try:
            _, report = establish_survival_model(seed=args.seed)
        except ModelValidationError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(report.describe())
        print("\nValidation passed — demonstrations allowed.")
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        report_path = MODELS_DIR / "validation_report.json"
        report_path.write_text(json.dumps(report_to_dict(report), indent=2) + "\n")
        print(f"validation report recorded at {report_path}")
        return 0

    if args.command == "scenario":
        model = _survival_model()  # the validation gate — no demonstration on a failing model
        if args.profile:
            profiles = [_profile_by_name(args.profile)]
        else:
            profiles = list(PRESETS)
        if len(profiles) == 1:
            engine = run_simulation(profile=profiles[0], model=model)
            _print_scenario_run(engine)
        else:
            print("Simulation Run comparison — the same ICU queue under each weight profile:")
            for profile in profiles:
                engine = run_simulation(profile=profile, model=model)
                _print_scenario_block(profile, engine)
        return 0

    if args.command == "demo":
        base = _base_time()
        model = _survival_model()
        profile = _profile_by_name(args.profile)
        engine = Engine(survival_model=model, clock=ManualClock(base), profile=profile)

        patients = _demand_ward(parser, args)
        if args.csv:
            print(f"loaded {len(patients)} patients from {args.csv}\n")

        _register_ward(engine, patients, snapshot=base)
        _print_queue(engine.snapshot("initial").entries)

        if args.advance_hours:
            print(f"\nafter {args.advance_hours:g} hours:\n")
            cast(ManualClock, engine._clock).advance(timedelta(hours=args.advance_hours))  # noqa: SLF001
            _print_queue(engine.snapshot("wait-elapsed").entries)

        _print_trail(engine)
        return 0

    if args.command == "allocate":
        base = _base_time()
        model = _survival_model()
        profile = _profile_by_name(args.profile)
        engine = Engine(survival_model=model, clock=ManualClock(base), profile=profile)

        patients = _demand_ward(parser, args)
        if args.csv:
            print(f"loaded {len(patients)} patients from {args.csv}\n")
        _register_ward(engine, patients, snapshot=base)

        engine.snapshot("bed-freed")
        recommendation = engine.recommend()
        print("Queued entries awaiting a bed:")
        _print_queue(recommendation.queue)
        print(f"\nRecommendation for the freed bed:\n  {recommendation.reasoning}\n")

        if args.deviate:
            chosen = _entry_spec(engine, args.deviate)
            decision = engine.deviate_allocation(
                recommendation, chosen, note=args.note
            )
        else:
            decision = engine.confirm_allocation(recommendation, note=args.note)

        change = _fmt_deviation_suffix(
            decision.allocated, decision.recommended, "deviation from"
        )
        print(
            f"{decision.outcome.value.capitalize()}: bed allocated to "
            f"{decision.allocated.patient_id}{change}"
        )
        if decision.note:
            print(f"  note: {decision.note}")
        print(
            f"  {len(engine.current_queue().entries)} entries remain in the queue"
        )

        _print_trail(engine)
        return 0

    if args.command == "serve":
        from .scenario import demo_engine
        from .web import create_dashboard_app

        if getattr(args, "patients", None) or getattr(args, "csv", None):
            base = _base_time()
            engine = Engine(
                survival_model=_survival_model(),
                clock=ManualClock(base),
                profile=_profile_by_name(args.profile),
            )
            patients = _demand_ward(parser, args)
            if args.csv:
                print(f"loaded {len(patients)} patients from {args.csv}")
            _register_ward(engine, patients, snapshot=base)
        else:
            engine = demo_engine(model=_survival_model())

        app = create_dashboard_app(engine)
        import uvicorn

        print(
            f"CareGrid dashboard: http://{args.host}:{args.port}/ "
            f"(profile {engine.current_queue().profile.name}, "
            f"{len(engine.trail())} trail records)"
        )
        uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
        return 0

    parser.error(f"unknown command '{args.command}'")
    return 2