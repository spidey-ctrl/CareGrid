# 10 — Survival signal vs the AUC ≥ 0.7 gate

**What to resolve:** the mandated feature set (SOFA + age + comorbidity) tops out around
AUC ≈ 0.68 median, just below the agreed gate tolerance of AUC ≥ 0.7, so the recorded-seed
model fails validation and every real-model demonstration stays blocked until this is
resolved.

Decided during ticket 08 with the maintainer: **keep the feature set as-is** (SOFA + age +
comorbidity − the dataset has no comorbidity column, so the third feature is a constant 0)
and track this tension here for later.

**Status:** needs-triage

## Evidence (ticket 08 implementation run)

- SOFA-only AUC ≈ 0.63; age-only ≈ 0.62; linear combination ≈ 0.67. GBM on SOFA + age +
  comorbidity count: median AUC ≈ 0.68 across split seeds (0.60–0.72); no depth/rate config
  pushes past 0.70 robustly.
- The recorded seed (20260818) lands at AUC ≈ 0.60 on the current config — an unlucky but
  honest fold, consistent with the seed-to-seed spread.
- Until resolution, the validation gate correctly blocks `caregrid demo` / `allocate` /
  `serve` from using the real model (see `.scratch/caregrid/issues/08-survival-model-harness.md`).
  The harness, recorded validation report, and gate are complete and honest.

## Candidate resolutions (choose one when this is triaged)

- **Enrich the training features** from the vitals/labs columns already in
  `data/X_train_2025.csv` (GCS, vitals, labs). Requires widening the `SurvivalModel`
  adapter seam so the engine can pass the extra features at predict time — a deliberate
  seam change beyond ticket 08's scope.
- **Relax the agreed tolerance** to what the three mandated features deliver robustly
  (e.g. AUC ≥ 0.65) — a change to the recorded gate constant in
  `src/caregrid/survival_model.py`.
- **Source a dataset with a genuine comorbidity column**, restoring the third feature's
  information.