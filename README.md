# CareGrid

An ICU bed-arbitration decision-support system. It scores patients waiting for
critical-care beds on severity, survival likelihood, and waiting time; re-ranks
the waitlist as the queue changes; and surfaces explainable rankings and
tie-breaks to the clinician, who makes the final allocation decision.

See `CONTEXT.md` for the domain language, and `docs/adr/` for architectural
decisions.

## Structure

- `src/caregrid/` — the domain engine (scoring, tie-breaking, audit trail) and CLI, plus the survival-model training/validation harness.
- `frontend/` — a Vite/React dashboard that displays the engine's output (read-only).
- `data/` — `X_train_2025.csv` / `y_train_2025.csv` (training dataset) and `data/models/` (trained booster + validation report).
- `tests/` — the test suite.

## Prerequisites

- Python 3.11+
- Node.js and npm (for the dashboard)
- The training dataset present at `data/X_train_2025.csv` and `data/y_train_2025.csv`

## Setup

```sh
python3 -m venv .venv
source .venv/bin/activate

# install the engine, CLI, web server, and the survival-model stack
pip install -e '.[web,model,test]'

# build the dashboard UI (static files served by the web server)
npm --prefix frontend install
npm --prefix frontend run build
```

Every subcommand trains (once, then cached), hold-out validates, and gates the
survival model first — a demo refuses to run on a model that fails the
validation tolerance. On first run this may take a little while; the validation
report is recorded to `data/models/validation_report.json`.

## Running

### Web dashboard

```sh
caregrid serve
```

Open http://127.0.0.1:8000/. Bind a different interface/port with
`--host` / `--port`. To serve a custom ward instead of the default Simulation
Run, pass patient specs or `--csv` (see `caregrid serve --help`).

During frontend development, run Vite with its dev server instead of the static
build:

```sh
npm --prefix frontend run dev   # proxies /api to the running `caregrid serve`
```

### CLI

Simulation Run replay (end-to-end audit trail: every snapshot's ranked queue
plus the arbitration decision), under all three weight profiles, or one with
`--profile`:

```sh
caregrid scenario
```

Print the ranked queue for a ward (default demo ward); re-rank after advance,
load a ward from CSV, or pass patients as `sofa×6,age[,comorbidities]` specs:

```sh
caregrid demo [--csv path.csv] [--profile Balanced]
caregrid demo 3,1,2,2,3,1,64,diabetes;COPD --advance-hours 24
```

Recommend and record an arbitration decision for a freed bed; deviate from the
recommendation with `--deviate`:

```sh
caregrid allocate
caregrid allocate --deviate patient-3 --note "younger, lower expected 30-day mortality"
```

Train, validate, and report the survival model standalone:

```sh
caregrid model
```

Run `caregrid <command> --help` for the full options (CSV schema, stagger
hours, profiles, etc.).

## Tests

```sh
pytest
mypy
```