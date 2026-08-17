PS-S03 CareGrid: Intelligent ICU Bed Arbitration and Critical Care
Prioritization Engine
Problem Statement
When critical-care capacity is exceeded, allocation decisions are made under time pressure,
drawing on clinical memory rather than any consistent, auditable framework for weighing one
patient's dependency against another's accumulated wait. The deficiency is not one of clinical
judgment but of structure — the absence of a transparent mechanism that can sit alongside that
judgment, surface its own reasoning, and hold up to scrutiny after the decision has already been
acted upon.
This problem statement concerns the design of a prioritization system that combines severity,
survival likelihood, and waiting time into a single comparable score, resolves near-equal cases
through a defined and explainable tie-breaking method, and updates dynamically as the patient
queue changes — new arrivals, freed beds — while leaving the final allocation decision with the
clinician.
Dependencies
• Access to relevant datasets (Hospital Beds Management, ICU Patient Outcome Prediction)
and/orsynthetic data generation to represent realistic queue compositions and edge casessuch
as ties.
• A scoring/ranking model design that combines multiple weighted factors (severity, survival
likelihood, waiting time) with a clearly defined normalization and weighting method.
• A deterministic rules engine or algorithm for tie-breaking, with each decision's reasoning
logged and retrievable for later review.
• A real-time (or near-real-time) update mechanism capable of re-ranking the queue as patients
arrive, are discharged, or beds free up.
• A dashboard/UI framework for queue visualization and a simulation environment to
demonstrate the arbitration logic end-to-end.
Minimum Requirements
• Patient profile model combining severity, survival likelihood, and waiting time into a single
comparable score.
• Priority ranking engine that updates as new patients arrive or beds free up.
• A defined tie-breaking method for near-equal cases, with reasoning shown.
• Dashboard showing current queue, rankings, and the "why" behind each rank.
• A simulated multi-patient scenario demonstrating the arbitration logic end-to-end.
• An audit/logging trail capturing how rankings changed over time and why.
• Sanity-check validation of the scoring model against outcomes in the ICU patient dataset.