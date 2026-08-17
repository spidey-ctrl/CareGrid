# 08 — Survival model harness + validation gate

**What to build:** the end-to-end behaviour this ticket makes work: a real gradient-boosted tree survival model, trained on the ICU Patient Outcome Prediction dataset (features SOFA + age + comorbidity; target survival to hospital discharge; CPU-only, no GPU), served through the adapter interface the engine already depends on, evaluated on a fixed 20% hold-out split (AUC-ROC, decile calibration, Brier score, recorded seed), with a validation gate that blocks any demonstration when the model fails the agreed tolerance.

**Blocked by:** 1 — Domain engine foundation

**Status:** ready-for-agent

- [ ] A CPU-trained gradient-boosted tree returns (survival probability, SHAP attribution) through the same adapter interface the engine uses, replacing the fake by configuration
- [ ] Held-out evaluation reports AUC-ROC, decile calibration, and Brier score with the split seed recorded
- [ ] Results are reproduceable from the recorded seed
- [ ] The validation gate (AUC ≥ 0.7, calibration within ±5% per decile) blocks demonstrations when the model fails it
- [ ] Requires no GPU