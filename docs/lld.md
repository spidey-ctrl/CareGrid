# CareGrid — Low-Level Design

A component- and interaction-level walkthrough of the `src/caregrid` codebase.
Read `CONTEXT.md` for the ubiquitous language and `docs/adr/` for the
architectural decisions this design implements.

Sources: `src/caregrid/engine.py`, `scenario.py`, `clock.py`, `survival.py`,
`sofa.py`, `profile.py`, `survival_model.py`, `cli.py`, `web.py`.

---

## 1. Architecture overview

```mermaid
flowchart TB
    subgraph Consumers["Consumers"]
        CLI["caregrid CLI<br/>model · scenario · demo · allocate · serve"]
        WEB["FastAPI dashboard<br/>/api/state · /api/trail · /api/events · /api/record/{id}"]
        SCEN["scenario.run_simulation<br/>(Simulation Run / seeded demo)"]
    end

    subgraph Domain["Domain: engine.py"]
        ENG["Engine<br/>the single public door"]
    end

    subgraph Adapters["Adapters the engine depends on"]
        CLK["Clock protocol<br/>to ManualClock (deterministic)"]
        MOD["SurvivalModel protocol<br/>predict(sofa, age, comorb)"]
        PROF["WeightProfile presets<br/>Severity-dominant / Balanced / Severity-heavy"]
    end

    subgraph Harness["Validation harness: survival_model.py"]
        SM["establish_survival_model<br/>XGBoost train to hold-out to gate to cache"]
        DATA[("data/<br/>X_train_2025.csv<br/>y_train_2025.csv<br/>models/")]
    end

    CLI --> ENG
    CLI --> SCEN
    WEB --> ENG
    SCEN --> ENG
    ENG --> CLK
    ENG --> MOD
    ENG --> PROF
    MOD -. trained adapter .-> SM
    SM --> DATA
    CLI -. model cmd .-> SM
```

Key property: the **engine never trains or runs a model** — it only talks to the
`SurvivalModel` protocol. The trained model (or the constant test stand-in) is
injected from outside; the validation harness is an offline gate, not runtime.

---

## 2. Module map

| Module | Responsibility | Public surface |
|---|---|---|
| `clock.py` | Time source abstraction | `Clock` (protocol), `ManualClock` |
| `sofa.py` | SOFA score value object | `Sofa` (`severity()`, `from_total()`) |
| `survival.py` | Model output + adapter seam | `SurvivalPrediction`, `SurvivalModel` (protocol) |
| `profile.py` | Weight presets | `WeightProfile`, `SEVERITY_DOMINANT`, `BALANCED`, `SEVERITY_HEAVY` |
| `engine.py` | All domain behaviour | `Engine`, all record types, exceptions |
| `scenario.py` | Scripted demo / seeded live view | `run_simulation`, `demo_engine` |
| `survival_model.py` | Train + validate + servable adapter | `establish_survival_model`, `TrainedSurvivalModel` |
| `cli.py` | CLI consumers | `main` |
| `web.py` | Read-only JSON API (FastAPI) | `create_dashboard_app` |

---

## 3. Domain object model

```mermaid
classDiagram
    class Sofa {
        +respiration: int
        +coagulation: int
        +liver: int
        +cardiovascular: int
        +central_nervous: int
        +renal: int
        +severity() int
        +from_total(total: int) Sofa
    }

    class SurvivalPrediction {
        +probability: float
        +attribution: Mapping[str, float]
    }

    class SurvivalModel~Protocol~ {
        <<protocol>>
        +predict(sofa, age, comorbidities) SurvivalPrediction
    }

    class Patient {
        +id: str
        +sofa: Sofa
        +age: int
        +comorbidities: tuple[str, ...]
        +survival: SurvivalPrediction
        +severity_factor() float
        +survival_factor() float
    }

    class QueueEntry~internal~ {
        +id: str
        +patient_id: str
        +created_at: datetime
    }

    class WeightProfile {
        +name: str
        +severity: float
        +survival: float
        +waiting: float
    }

    class EntryView {
        +entry_id: str
        +patient_id: str
        +score: float
        +severity_factor: float
        +survival_factor: float
        +waiting_factor: float
        +survival_probability: float
        +survival_attribution: Mapping
        +waiting_time: timedelta
        +created_at: datetime
        +profile: WeightProfile
        +tie_break_reason: str
    }

    class QueueView {
        +profile: WeightProfile
        +wait_horizon: timedelta
        +entries: tuple[EntryView]
    }

    class RankingSnapshot {
        +snapshot_id: int
        +captured_at: datetime
        +trigger: str
        +profile: WeightProfile
        +wait_horizon: timedelta
        +entries: tuple[EntryView]
    }

    class Recommendation {
        +trigger: str
        +entry: EntryView
        +queue: tuple[EntryView]
        +reasoning: str
    }

    class ArbitrationDecision {
        +decision_id: int
        +recorded_at: datetime
        +trigger: str
        +outcome: CONFIRMED | DEVIATION
        +profile / wait_horizon
        +queue: tuple[EntryView]
        +recommended / allocated: EntryView
        +reasoning: str
        +note: str
    }

    class Event {
        +id: int
        +occurred_at: datetime
        +kind: ARRIVAL|REMOVAL|PROFILE_CHANGE|RERANK|BED_FREED|ALLOCATION
        +detail: str
    }

    Patient --> Sofa
    Patient --> SurvivalPrediction
    SurvivalModel <.. Patient : survival computed at registration
    Patient "1" --> "0..*" QueueEntry : open_entry / close_entry
    EntryView o-- Patient
    EntryView --> WeightProfile
    QueueView "*" --> EntryView
    RankingSnapshot "*" --> EntryView
    Recommendation --> EntryView
    ArbitrationDecision "*" --> EntryView
```

Two distinct "patients": **`Patient`** is the identity + clinical attributes
(persists across visits) and **`QueueEntry`** is one waitlist occupancy carrying
`created_at` (resets per visit). `EntryView` is the **computed** projection of a
queue entry at an instant — score, factors, SHAP attribution — which is what all
ranking, snapshots, and decisions are built from.

### Engine internal state

```mermaid
flowchart LR
    subgraph S["Engine internals"]
        P["_patients<br/>dict[PatientId, Patient]"]
        Q["_entries<br/>dict[EntryId, QueueEntry]"]
        T["_trail<br/>tuple[RankingSnapshot | ArbitrationDecision]<br/>append-only, shared id counter +1/trail+2/…"]
        E["_events<br/>tuple[Event]<br/>append-only"]
        W["_profile (WeightProfile)<br/>_wait_horizon (default 24h)"]
    end
    Q --> P
    T -. current rank .-> Q
    E --> Q
    W --> T
```

Snapshots and decisions share the single `_next_trail` counter, so the trail is
one chronological interleaved sequence (e.g. `1 ward-opened, 2 removal,
3 tip-arrival, 4 bed-freed, 5 decision, 6 post-allocation`).

---

## 4. Scoring, ranking, and the Tie-Break Cascade

### Priority score computation (`engine._entry_view`)

```mermaid
flowchart TD
    A["For each QueueEntry at now = clock.now()"] --> B["severity_factor = SOFA total / 24"]
    A --> C["survival_factor = Patient.survival.probability"]
    A --> D["waiting_time = now − created_at"]
    D --> E["waiting_factor = min(1.0, (waiting_time / 24h horizon)²)<br/>saturating quadratic"]
    B --> F["score = w_sev·severity + w_surv·survival + w_wait·waiting<br/>under the active WeightProfile"]
    C --> F
    E --> F
```

### Deterministic sort key (`engine._rank`)

```mermaid
flowchart TD
    F["score computed for every live entry"] --> S["sort by the tuple key:"]
    S --> K["(−round(score, 2),<br/>−severity_factor, −survival_factor,<br/>−waiting_factor, created_at)"]
    K --> A2["_annotate_ties groups<br/>equal-round(...)-score entries"]
    A2 --> R["return ranked EntryView list"]
```

The 2-decimal **rounding** is what counts as a "near-tie"; the next four sort
keys *are* the cascade, applied implicitly. `_annotate_ties` then walks each
equal-rounded group and stamps the winner of each adjacent pair with the stage
that decided it.

### Tie-Break Cascade reasoning (`engine._tie_break_reason`)

```mermaid
flowchart TD
    A["Adjacent pair 'above' vs 'below',<br/>equal after rounding to 2dp"] --> B{"severity_factor differs?"}
    B -->|yes| C["higher severity wins<br/>(reason recorded)"]
    B -->|no| D{"survival_factor differs?"}
    D -->|yes| E["higher survival wins"]
    D -->|no| F{"waiting_factor differs?"}
    F -->|yes| G["longer wait wins"]
    F -->|no| H{"created_at differs?"}
    H -->|yes| I["earlier entry wins"]
    H -->|no| J["fully tied — nothing recorded"]
```

### Weight profiles (`profile.py`)

| Profile | severity | survival | waiting |
|---|---|---|---|
| Severity-dominant (default) | 0.5 | 0.3 | 0.2 |
| Balanced | 0.4 | 0.3 | 0.3 |
| Severity-heavy | 0.6 | 0.25 | 0.15 |

Every `EntryView`, snapshot, and decision carries the `profile` it was scored
under, so any score is traceable to its profile.

---

## 5. Command flow — register → rank → arbitrate

```mermaid
sequenceDiagram
    actor Clinical as Clinician
    participant Consumer as Consumer<br/>(CLI / scenario / web)
    participant Engine as Engine
    participant Model as SurvivalModel adapter

    rect rgb(240,248,255)
        Note over Consumer,Engine: Admission
        Consumer->>Engine: register_patient(sofa, age, comorbidities)
        Engine->>Model: predict(sofa, age, comorbidities)
        Model-->>Engine: SurvivalPrediction(probability, attribution)
        Engine-->>Consumer: patient-1
        Consumer->>Engine: open_entry(patient-1)
        Engine->>Engine: created_at = clock.now() · ARRIVAL event
        Engine-->>Consumer: entry-1
    end

    rect rgb(255,248,240)
        Note over Consumer,Engine: Every re-rank
        Consumer->>Engine: snapshot(trigger)  (ward-opened, removal, …)
        Engine->>Engine: _rank(now) → sorted EntryViews + tie reasons
        Engine-->>Consumer: RankingSnapshot appended to trail · RERANK event
    end

    rect rgb(240,255,240)
        Note over Consumer,Engine: Arbitration
        Consumer->>Engine: recommend()
        Engine->>Engine: rank queue, top entry or EmptyQueue
        Engine-->>Consumer: Recommendation(entry, queue, reasoning)
        Consumer->>Engine: confirm_allocation(recommendation [, note])
        Engine->>Engine: re-rank, verify recommended still queued (StaleRecommendation)
        Engine->>Engine: ArbitrationDecision(CONFIRMED) → trail · ALLOCATION event
        Engine->>Engine: close_entry(allocated) · REMOVAL event
        Engine-->>Consumer: ArbitrationDecision
    end
```

The clinician-path detail (`engine._allocate`):

```mermaid
flowchart TD
    A["recommend() returns top-ranked EntryView"] --> B{"confirm_allocation<br/>or<br/>deviate_allocation?"}
    B -->|confirm| C["allocated = recommended entry"]
    B -->|deviate| D{"allocated == recommended?"}
    D -->|yes| E["InvalidDeviation — use confirm instead"]
    D -->|no| F{"allocated rank ≤ recommended rank?"}
    F -->|yes| G["InvalidDeviation — not below the recommendation"]
    F -->|no| C2["allocated = clinician's pick<br/>(recorded as DEVIATION)"]
    C --> H["re-rank · verify recommended still present<br/>(else StaleRecommendation)"]
    C2 --> H
    H --> I["append ArbitrationDecision to trail"]
    I --> J["close the allocated entry"]
```

---

## 6. The Simulation Run — how initial data is seeded

The seeded "initial data" is **hand-engineered, not generated**. A five-member
cast plus a deterministic `ManualClock` plays a fixed timeline; no PRNG is
involved in the queue (the only configurable seed in the codebase is the
model's hold-out split, §7).

```mermaid
flowchart LR
    subgraph Cast["Loaded cast (scenario.py)"]
        LW["patient-1 LONG_WAITER<br/>SOFA 10 · 74y"]
        DR["patient-2 DRIFTER<br/>SOFA 12 · 50y · removed mid-run"]
        TL["patient-3 TIE_LOWER<br/>SOFA 11 · 62y"]
        TH["patient-4 TIE_HIGHER<br/>SOFA 13 · 47y"]
        TP["patient-5 TIP<br/>SOFA 20 · 41y"]
    end
    Cast --> RUN["run_simulation(profile=SEVERITY_DOMINANT,<br/>model = trained model or _DemoSurvivalModel p=0.7)"]
    RUN --> ENG2["Engine + ManualClock(T0 = 2026-01-01 08:00 UTC)"]
```

### Timeline (`T0` = 2026-01-01 08:00 UTC, `hour` = 1h increments)

```mermaid
timeline
    title Simulation Run — staggered admissions on a ManualClock
    T0 − 36h : patient-1 LONG_WAITER admits — waits past the 24h horizon
    T0 − 20h : patient-2 DRIFTER admits
    T0 − 18h : snapshot #1 WARD_OPENED
    T0 − 12h : patient-3 TIE_LOWER admits (lower severity, longer waiter)
    T0 − 6h : patient-4 TIE_HIGHER admits
    T0 − 4h : close DRIFTER · snapshot #2 REMOVAL
    T0 : patient-5 TIP admits · snapshot #3 TIP_ARRIVAL (near-tie resolves on severity)
    T0 : snapshot #4 BED_FREED
    T0 : confirm_allocation(recommend()) → decision #5
    T0 : snapshot #6 POST_ALLOCATION
    T0 + 3h : clock.advance — live view shows rank drift
```

Two survival sources, deliberately:
- **`_DemoSurvivalModel`** — constant `p = 0.7` with fixed attributions; keeps
  tests and dashboard-tests deterministic and the edge cases provable by hand.
- **`TrainedSurvivalModel`** — the validated booster, injected on demonstration
  paths (CLI, dashboard) via `establish_survival_model` (the ticket-8 gate).
  Structure of the scenario is identical; numbers under the real model differ.

`demo_engine(model)` (web.py's seed) is just `run_simulation` under the default
Severity-dominant profile.

---

## 7. Survival-model training / validation / gate

```mermaid
flowchart TD
    A["data/X_train_2025.csv + y_train_2025.csv"] --> B["_load_rows<br/>headers normalised · missing SOFA (−1) → NaN<br/>rows with non-0/1 death outcome dropped<br/>survival = 1 − death"]
    B --> C["_stratified_split(seed=20260818, fraction=0.8)<br/>separate survivors/deaths · rng.shuffle · 80/20"]
    C --> D["fit_booster<br/>xgboost binary:logistic, max_depth 3, eta 0.05,<br/>n_jobs=1 for bit-for-bit reproducibility"]
    D --> E["hold-out predictions + labels"]
    E --> F["validation_report: AUC, Brier, decile calibration"]
    F --> G{"report.passed()?<br/>AUC ≥ 0.60 AND calibration MAE ≤ 0.06"}
    G -->|no| H["ModelValidationError —<br/>demonstrations blocked"]
    G -->|yes| I["TrainedSurvivalModel cached per (seed, csv)<br/>module-level _ESTABLISHED dict"]
    I --> J["servable adapter: predict() →<br/>probability + SHAP pred_contribs attribution"]
```

`TrainedSurvivalModel.predict` feeds `[sofa_total, age, comorbidity_count]` to
the booster and reads native `pred_contribs` as the SHAP attribution (ADR-0004).

---

## 8. Read side — web dashboard and CLI

### Web (FastAPI, read-only)

```mermaid
flowchart LR
    subgraph API["/api endpoints"]
        S["state"] 
        T["trail"]
        E["events"]
        R["record/id"]
        SN["snapshot/id"]
        H["patient/id/history"]
    end
    subgraph EngineReads["engine reads"]
        EQ["current_queue() + now()"]
        ET["trail()"]
        EE["events()"]
        ER["_record_by_id / snapshot_at / decision_at"]
        EH["patient_rank_history()"]
    end
    API --> EngineReads
    WEB2["React build (frontend/dist)"]
    API --- WEB2
    EngineReads -. read-only .-> D["engine"]
```

Every value is derived from engine reads — the web layer performs no decision
logic. `_movement_by_entry` compares the live queue order against the last
snapshot's (up / down / unchanged / new) purely as a projection.

### CLI subcommands

| Command | Behaviour |
|---|---|
| `model` | Train + validate + record `data/models/validation_report.json` |
| `scenario` | Replay the Simulation Run (all three profiles, or `--profile`) |
| `demo` | Print ranked queue (default ward, `PATIENT` specs, or `--csv`); `--advance-hours` re-ranks |
| `allocate` | Recommend + record the decision; `--deviate` for a conscious deviation with `--note` |
| `serve` | Launch the FastAPI dashboard over a seeded engine |

---

## 9. Test strategy hooks the design makes possible

The seams are deliberate:

- **`Clock` protocol / `ManualClock`** — time-bombs (hour boundaries, horizon
  saturation) are exact.
- **`SurvivalModel` protocol** — the stand-in makes any test deterministic
  without training; the trained adapter is validated separately.
- **Immutable record types** — snapshots/decisions/events are compared for
  equality, and the `trail()` tuple is asserted in order.
- **Frozen `Sofa` / `WeightProfile`** — no accidental mutation of shared presets.

---

## 10. Failure modes

| Condition | Exception | Raised by |
|---|---|---|
| register/open on unknown patient or entry | `UnknownPatient` / `UnknownEntry` | `open_entry`, `close_entry`, `patient_rank_history` |
| snapshot/decision lookup miss | `UnknownSnapshot` / `UnknownDecision` | `snapshot_at`, `decision_at` |
| recommend with empty queue | `EmptyQueue` | `recommend` |
| recommended entry left the queue | `StaleRecommendation` | `_allocate` |
| confirm-vs-deviate misuse or not-above-recommendation deviation | `InvalidDeviation` | `deviate_allocation`, `_allocate` |
| model failed validation gate | `ModelValidationError` | `establish_survival_model` (blocks demo/scenario/serve) |