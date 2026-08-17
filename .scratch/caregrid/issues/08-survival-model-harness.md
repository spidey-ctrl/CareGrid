# 08 — Survival model harness + validation gate

**What to build:** the end-to-end behaviour this ticket makes work: a real gradient-boosted tree survival model, trained on the ICU Patient Outcome Prediction dataset (features SOFA + age + comorbidity; target survival to hospital discharge; CPU-only, no GPU), served through the adapter interface the engine already depends on, evaluated on a fixed 20% hold-out split (AUC-ROC, decile calibration, Brier score, recorded seed), with a validation gate that blocks any demonstration when the model fails the agreed tolerance.

**Blocked by:** 1 — Domain engine foundation

**Status:** resolved (implemented Aug 18 2026)

- [x] A CPU-trained gradient-boosted tree returns (survival probability, SHAP attribution) through the same adapter interface the engine uses, replacing the fake by configuration — `TrainedSurvivalModel` in `src/caregrid/survival_model.py`, wired through `cli._survival_model()` and `scenario.demo_engine(model=…)`
- [x] Held-out evaluation reports AUC-ROC, decile calibration, and Brier score with the split seed recorded — `caregrid model`, report persisted to `data/models/validation_report.json`
- [x] Results are reproduceable from the recorded seed (`SPLIT_SEED = 20260818`, single-threaded training)
- [x] The validation gate blocks demonstrations when the model fails it
- [x] Requires no GPU
- [ ] Tolerance amended by maintainer decision: the original bar (AUC ≥ 0.7 AND ±5% per decile) was unreachable for the mandated feature set — see `issues/10-model-signal-vs-validation-gate.md` for the evidence and the resolution