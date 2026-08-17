# CareGrid — Intelligent ICU Bed Arbitration and Critical Care Prioritization Engine

Status: ready-for-agent

Feature: PS-S03
Tracker: local markdown — see `docs/agents/issue-tracker.md`
Related docs: glossary at `CONTEXT.md`, decisions at `docs/adr/0001`–`0004`

## Problem Statement

When critical-care capacity is exceeded, allocation decisions are made under time pressure, drawing on clinical memory rather than any consistent, auditable framework for weighing one patient's dependency against another's accumulated wait. The deficiency is not one of clinical judgment but of structure — there is no transparent mechanism that can sit alongside that judgment, surface its own reasoning, and hold up to scrutiny after the decision has already been acted upon.

The clinician is left holding a ranked intuition and a queue that changes beneath them; there is no way to answer, after the fact, "who ranked where, why, and who changed it."

## Solution

CareGrid scores every queueing patient into a single comparable Priority Score combining Severity (SOFA), Survival Likelihood (model-predicted, explained by SHAP), and Waiting Time (a saturating quadratic curve); re-ranks the ICU waitlist as the queue changes; resolves near-equal scores through a deterministic, explainable Tie-Break Cascade; and records an immutable Ranking Snapshot on every re-rank so the "why" behind each rank — and each bed assignment — is retrievable forever.

When a bed frees up, the system recommends the top candidate with its full reasoning; the clinician confirms the allocation or consciously deviates, with the deviation recorded in the same audit trail. The final decision is always the clinician's.

The whole loop — from a loaded queue through re-ranks, tie-breaks, and a bed allocation — is demonstrated end-to-end through a dashboard and a synthetic Simulation Run, with the survival model's fitness sanity-checked against real ICU outcomes before any demonstration is allowed.

## User Stories

### Scoring the queue

1. As a clinician, I want each waiting patient reduced to a single comparable Priority Score, so that I can compare patients' urgency at a glance.
2. As a clinician, I want the Priority Score decomposed into its severity, survival, and waiting-time contributions, so that I can see *why* one number is higher than another.
3. As a clinician, I want severity derived from the SOFA score (0–24, six organ systems), so that I can trust the acuity signal as the ICU-native standard.
4. As a clinician, I want severity normalized linearly as SOFA/24, so that the factor bar is directly interpretable.
5. As a clinician, I want survival likelihood as a predicted probability of survival from a gradient-boosted tree model, so that a patient's expected outcome, not just their acuity, shapes priority.
6. As a clinician, I want higher survival likelihood to *raise* priority among equally severe patients, so that the bed goes to the patient most likely to benefit from it.
7. As a clinician, I want each survival prediction accompanied by SHAP attributions, so that I can see which features (SOFA components, age, comorbidities) drove that number.
8. As an auditor, I want the survival predictions traceable to a single trained model with a recorded validation report, so that the ranking's foundation is reproduceable.

### Weighting and waiting

9. As a clinician, I want the composite Priority Score computed as an additive weighted sum, so that every point on the score can be attributed to a visible factor.
10. As a clinician, I want waiting time normalized by a saturating quadratic curve `min(1,(t/T)²)` with a 24-hour policy horizon, so that short waits barely matter, long waits rise steeply, and no patient can run away on wait time alone.
11. As a clinician, I want the wait horizon to be a declared policy parameter recorded on every ranking, so that wait behavior is auditable, not incidental.
12. As a clinician, I want a patient who has waited past the horizon to be fully "wait-exhausted" (capped), so that an unending wait does not ossify them forever above a newly arriving severe case.
13. As a clinician, I want the three weight profiles available as declared presets — Severity-dominant (50/30/20), Balanced (40/30/30), Severity-heavy (60/25/15) — so that I can compare how policy stance changes the queue.
14. As a demonstrator, I want to select a weight profile for a run and see all three profiles demonstrated against the same scenario, so that the design's sensitivity to policy is visible.
15. As an auditor, I want every Ranking Snapshot to record which weight profile produced it, so that any historical score is traceable to its policy context.

### Re-ranking and dynamics

16. As a clinician, I want the queue to re-rank immediately when a new patient is placed on the waitlist, so that an arriving severe patient is considered at once.
17. As a clinician, I want the queue to re-rank when a patient is removed (discharged, transferred, or deceased), so that the list always reflects who actually waits.
18. As a clinician, I want the queue to re-rank when a bed frees up, so that the arbitration moment always sees the live ordering.
19. As a clinician, I want the queue to re-rank when a patient's clinical attributes change or a weight profile is switched, so that stale assessments never gate allocation.
20. As a clinician, I want the queue to re-rank periodically (5-minute clock) even with no events, so that slow waiting-time drift never leaves a stale order in place.
21. As a clinician, I want each re-rank to recompute every Queue Entry's score and reorder, so that the full list is internally consistent at each instant.

### Tie-breaking

22. As a clinician, I want near-equal Priority Scores (equal after rounding to 2 decimal places) to be resolved by a defined, deterministic Tie-Break Cascade, so that the outcome does not depend on run order or chance.
23. As a clinician, I want the cascade to prefer, in order: higher severity, then higher survival, then longer wait, then earlier Queue Entry creation, so that the tie-break encodes defensible clinical values.
24. As a clinician, I want the cascade's reasoning for every stage shown, so that I can read exactly why two patients with equal scores were ordered one way.
25. As a clinician, I want the tie-break to produce identical output on replay of the same queue, so that the decision is provably deterministic.

### Arbitration and the human loop

26. As a clinician, I want the system to recommend the top-ranked Queue Entry with its full score and reasoning the moment a bed frees up, so that my final call is fully informed.
27. As a clinician, I want to confirm an allocation at the click of a button, so that the bed assignment and its reasoning land in the audit trail.
28. As a clinician, I want to consciously deviate — allocate a lower-ranked patient — and have that deviation recorded as such, so that I always remain answerable to my own judgment, and the system never overrides me.
29. As a clinician, I want the queue to be searchable and patient rank histories viewable, so that I can review "when did this patient's rank move, and why."
30. As an auditor, I want every Arbitration Decision — recommend, confirm, and deviation — stored in the same append-only trail as the Ranking Snapshots, so that the full decision trail for a bed is one contiguous story.

### Dashboard

31. As a clinician, I want a live ranked queue showing every patient with their Priority Score and the three factor bars, so that I can assess the whole list at a glance.
32. As a clinician, I want a one-line "why this rank" rationale per row, so that the ranking is self-explanatory without opening anything.
33. As a clinician, I want the survival model's top SHAP attributions visible per patient, so that I can sanity-check whether the model's reasons make clinical sense.
34. As a clinician, I want a rank-movement indicator (up/down/unchanged since the last snapshot), so that I can see the queue's dynamics, not just its position.
35. As a clinician, I want an active weight-profile badge on the view, so that I always know which policy stance I'm reading.
36. As a clinician, I want the tie-break cascade's reasoning surfaced inline on tied rows, so that near-equal cases never read as arbitrary.
37. As a clinician, I want a side panel listing the event feed (arrivals, removals, freed beds, re-ranks), so that I can see what moved the queue.
38. As a reviewer, I want a replay slider over the audit trail, so that I can walk the queue's history backwards and forwards through time.
39. As a reviewer, I want to load any past Ranking Snapshot and see the exact queue, scores, profile, and horizon at that moment, so that review is a read, not a reconstruction.

### Audit trail

40. As an auditor, I want an immutable Ranking Snapshot appended on every re-rank, so that nothing can be silently edited after the fact.
41. As an auditor, I want each snapshot to contain the full ordered queue with per-entry scores and factor breakdowns, so that any past moment is fully reconstructable from the file itself.
42. As an auditor, I want each snapshot to contain the survival term's SHAP attribution, the weight profile and wait horizon, and the trigger that caused the re-rank, so that context never requires archaeology.
43. As an auditor, I want the trail append-only, so that the sequence of decisions is a provable chain of records.

### Simulation and validation

44. As a demonstrator, I want a Simulation Run that generates a realistic ICU-style queue with deliberately loaded edge cases — near-ties, an exhausted long-waiter, arrivals that tip a tie — so that the arbitration logic is shown under pressure.
45. As a demonstrator, I want a run to play events (arrivals, removals, a freed bed) through the engine and produce the Ranking Snapshot trail, so that the end-to-end flow is demonstrated on demand.
46. As a demonstrator, I want the same scenario runnable under each weight profile for comparison, so that the policy sensitivity of an identical queue is out in the open.
47. As a model engineer, I want the survival model trained on the real ICU Patient Outcome Prediction dataset (CPU-only, no GPU), so that the model is grounded in real outcomes rather than simulation.
48. As a model engineer, I want the survival model's target defined as survival to hospital discharge, so that the prediction captures the effect of ICU care beyond the ward doors.
49. As a model engineer, I want the survival model validated on a fixed 20% hold-out split — discrimination (AUC-ROC), calibration per decile, and Brier score — with the split seed and results recorded, so that the sanity check is reproduceable by a reviewer.
50. As a demonstrator, I want a demonstration gated on that validation passing an agreed tolerance (AUC ≥ 0.7, calibration within ±5% per decile), so that no scenario is shown on top of a model that fails its sanity check.

## Implementation Decisions

All decisions below were settled in a domain-modeling/grilling session and are recorded in the glossary (`CONTEXT.md`) and ADRs (`docs/adr/0001`–`0004`). Terms follow the glossary.

### Module shape — one engine, thin consumers

- **Domain engine** — the core module owning all arbitration logic: Patient and Queue Entry lifecycle, Priority Score computation, weight-profile binding, re-ranking, Tie-Break Cascade, Ranking Snapshot writing, and the Arbitration Decision workflow (recommend → confirm/deviation). It is the only behavioral surface in the system.
- **Survival model adapter** — a narrow interface the engine depends on: `predict_survival(sofa_components, age, comorbidity) → { probability, shap_attribution }`. The production implementation wraps the trained gradient-boosted tree; tests substitute a deterministic fake through this interface. The engine treats survival as an injected dependency and is fully testable without the trained artifact.
- **Simulation environment** — builds a Simulation Run: generates the ICU-style queue with edge cases and plays events through the domain engine, consuming the snapshot trail it produces. No logic of its own beyond scenario generation.
- **Dashboard** — a read-only consumer of the engine's queries and of the snapshot trail; renders the live queue, factor breakdowns, SHAP attributions, tie-break reasoning, event feed, and history replay.
- **Validation harness** — trains/evaluates the survival model on the fixed hold-out split and gates demonstrations on the agreed tolerance. Standalone; does not sit in the engine's runtime path.

### Engine contract (from the session; the API that tests and consumers operate)

- **Commands**: register Patient; open a Queue Entry for a Patient; close a Queue Entry (discharge/transfer/decease); update a Patient's clinical attributes (SOFA components, age, comorbidities); free a bed; select a Weight Profile; confirm an allocation; record a deviation.
- **Queries**: current ranked queue; a single Ranking Snapshot; a Patient's rank history across snapshots; the event stream.
- **Event behavior**: per the session, every command that changes queue state returns the resulting ranked queue — each Queue Entry with its Priority Score and the three-factor breakdown (severity, survival, wait), plus survival SHAP attributions, the active weight profile, and the current wait horizon. An event triggering a re-rank also appends a Ranking Snapshot. Thus "a new patient event lists all patients with score and all other information," exactly as the user specified.

### Scoring formulas (settled in the session)

- **Priority Score** = w₁·(SOFA/24) + w₂·p_surv + w₃·min(1,(t/T)²), where p_surv is the model's predicted survival probability and t is the Queue Entry's Waiting Time.
- **Wait horizon** T = 24 hours, a declared policy parameter recorded on every snapshot.
- **Weight Profiles**: Severity-dominant (0.5/0.3/0.2), Balanced (0.4/0.3/0.3), Severity-heavy (0.6/0.25/0.15). Scoped per Simulation Run; the active profile is logged with every snapshot.
- **Tie-Break Cascade**: fires when two scores are equal after rounding to 2 decimal places; resolves in order — higher severity, then higher survival, then longer wait, then earlier Queue Entry creation. Each stage's reasoning is surfaced in the dashboard and recorded in the snapshot.

### Dynamics

- **Re-ranking triggers**: any discrete event (new Queue Entry, removal, freed bed, clinical attribute update, weight-profile change) plus a scheduled 5-minute recompute, so waiting-time drift never leaves a stale order.
- **Allocation flow**: on a freed bed the engine recommends the top-ranked Queue Entry; the clinician confirms or deviates. Both outcomes are recorded as Arbitration Decisions in the same append-only trail. The system never auto-allocates (ADR-0002).

### Audit

- **Ranking Snapshot**: an immutable, append-only record written on every re-rank — full ordered queue with per-entry score and factor breakdown, survival SHAP attribution, weight profile and wait horizon in effect, the trigger, and tie-break reasoning. Arbitration Decisions land in the same trail (ADR-0003).

### Data and model

- **Survival model**: gradient-boosted tree (e.g. XGBoost/LightGBM), CPU-only, no GPU (ADR-0004); trained on the ICU Patient Outcome Prediction dataset; features SOFA + age + comorbidity; target survival to hospital discharge; SHAP for attribution.
- **Scenario data**: real-trained model + synthetic Simulation Runs with deliberately loaded edge cases (near-ties, exhausted long-waiters, tipping arrivals).
- **Validation**: fixed 20% hold-out split with recorded seed; reports AUC-ROC, decile calibration, and Brier score; demonstration gated on AUC ≥ 0.7 and calibration within ±5% per decile.

## Testing Decisions

- **Definition of a good test**: a test exercises external behavior through the domain engine API only — it issues commands, observes returned ranked queues and snapshots, and asserts on outcomes (order, scores, tie-break reasons, snapshot contents). Tests must not inspect engine internals, which is what keeps the single seam honest.
- **The single seam**: the domain engine's command/query API is the one test surface. Every behavior listed in the User Stories — scoring, tie-breaking, re-ranking, allocation records, snapshot integrity — is asserted as a whole-flow behavior through this door.
- **Survival model in tests**: injected through the adapter interface as a deterministic fake (fixed probabilities and SHAP vectors). No test requires the trained model or the dataset. The real model's fitness is covered by the separate hold-out validation harness, not by unit tests.
- **What will be tested**:
  - Scoring: exact Priority Score values for constructed SOFA/survival/wait inputs under each weight profile; the wait curve's early flatness, scaling, and saturation at the horizon.
  - Tie-Break Cascade: near-equal pairs resolving at every cascade stage; determinism on identical replay; scores beyond 2-decimal equality left untouched by the cascade.
  - Re-ranking: order changes on every trigger type (arrival, removal, freed bed, attribute update, profile switch, scheduled recompute) and the snapshots appended per re-rank.
  - Arbitration Decision: freed bed → recommendation of top candidate → confirm and deviation paths, both recorded; deviation never auto-allowed.
  - Audit trail: snapshot immutability (append-only), content completeness against a known event sequence, and a Patient's rank history reconstructable across snapshots.
- **Prior art**: the repo is greenfield — no application code or tests exist yet. The conventions above are established by this spec and are themselves the template for all future tests in this codebase.

## Out of Scope

- Real hospital integration: EHR feeds, live bed-availability APIs, production deployment, or connectivity with actual hospital systems.
- Clinical validation, ethical approval, or regulatory certification of the scoring policy for real patient-facing use.
- Auto-allocation of beds; the final decision is always the clinician's (ADR-0002).
- Deep-learning or GPU-based survival modeling; the survival model is CPU gradient boosting (ADR-0004).
- Multi-context/multi-tenant architecture; this is a single-context system.
- Outpatient, non-ICU, or long-term-care triage.
- Mobile clients or real-time push infrastructure.

## Further Notes

- The glossary in `CONTEXT.md` is authoritative for vocabulary: Patient, Queue Entry, Waiting Time, Severity, Survival Likelihood, Priority Score, Weight Profile, Tie-Break Cascade, Ranking Snapshot, Arbitration Decision, Simulation Run.
- ADRs `0001`–`0004` record the four decisions most likely to be re-litigated: the greater-benefit survival direction, the clinician-confirms allocation boundary, snapshot-per-re-rank auditing, and the CPU-only model choice. Future work must flag, not silently override, contradictions.
- The engine being the only seam means the dashboard and simulation environment should be kept deliberately thin — any logic that grows meaningful reasoning there should be pulled back into the engine, or the seam proposition revisited explicitly.