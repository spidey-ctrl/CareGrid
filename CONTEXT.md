# CareGrid

An ICU bed-arbitration decision-support system. It scores patients waiting for critical-care beds on severity, survival likelihood, and waiting time; re-ranks the waitlist as the queue changes; and surfaces explainable rankings and tie-breaks to the clinician, who makes the final allocation decision.

## Language

**Patient**:
A person requiring or under consideration for ICU care. Carries the identity and clinical attributes (severity, survival likelihood) that persist across queue visits.
_Avoid_: Client, subject, case

**Queue Entry**:
A patient's current occupancy of the ICU waitlist. Carries the accumulated waiting time and the live priority score, computed from the patient's attributes and time-in-queue.
_Avoid_: Slot, candidacy, queue item

**Waiting Time**:
The time accrued by a Queue Entry since its creation, while the patient remains on the ICU waitlist. Resets on each new Queue Entry.
_Avoid_: Wait, queue time, time-on-list

**Severity**:
A Patient's acuity as measured by the SOFA score (0–24), computed from six organ-system components. Higher is sicker.
_Avoid_: Acuity, sickness, criticality

**Survival Likelihood**:
A Patient's predicted probability of surviving, output by a gradient-boosted tree survival model (features: SOFA + age + comorbidity) trained on the ICU Patient Outcome Prediction dataset; SHAP values make each prediction explainable.
_Avoid_: Mortality risk, prognosis

**Priority Score**:
The live composite score of a Queue Entry: an additive weighted sum `w₁·n(severity) + w₂·n(survival) + w₃·n(wait)`, each factor normalized 0–1 (severity as SOFA/24, survival as predicted probability, wait as a saturating quadratic `min(1,(t/T)²)` with a 24h policy horizon). Higher means higher priority.
_Avoid_: Rank, composite, weighted score

**Weight Profile**:
A named preset of score weights — Severity-dominant (50/30/20), Balanced (40/30/30), Severity-heavy (60/25/15). Scoped to a simulation run and logged with every ranking snapshot so any score is traceable to its profile.
_Avoid_: Configuration, parameter set

**Tie-Break Cascade**:
The deterministic rule that resolves near-equal Priority Scores (equal after rounding to 2 decimals): higher severity, then higher survival, then longer wait, then earlier Queue Entry creation. Each stage's reason is shown to the clinician.
_Avoid_: Tie-break, resolver, near-tie rule

**Ranking Snapshot**:
An immutable, append-only audit record written on every re-rank: the ordered queue with each entry's score and factor breakdown, the survival term's SHAP attribution, the Weight Profile and wait horizon in effect, the trigger, and any Tie-Break Cascade reasoning. Allocation records land in the same trail.
_Avoid_: Log entry, audit record, state dump

**Arbitration Decision**:
The allocation of a freed bed to a Queue Entry, made when the system recommends the top candidate and the clinician confirms — or consciously deviates, the deviation being recorded in the audit trail. The final call is always the clinician's.
_Avoid_: Assignment, auto-allocation, bed release

**Simulation Run**:
A self-contained demonstration scenario: a generated ICU-style queue with deliberately loaded edge cases (near-ties, exhausted long-waiters, tipping arrivals) played under a chosen Weight Profile against the trained survival model, producing the ranking snapshots that demo the arbitration end-to-end.
_Avoid_: Demo, test episode, replay
