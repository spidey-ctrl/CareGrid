# 01 — Domain engine foundation

**What to build:** the end-to-end behaviour this ticket makes work, from the user's perspective: register a Patient (carrying severity from SOFA and a survival prediction sourced through the survival adapter), open a Queue Entry for them, see the priority score computed, and query the ranked queue — every path through the engine's single public door. Survival arrives through an injectable adapter so the engine is testable with a deterministic fake, no trained model in sight.

**Blocked by:** None — can start immediately

**Status:** ready-for-agent

- [ ] A Patient can be registered with SOFA components, age, and comorbidities, returning a stable identity
- [ ] A Queue Entry can be opened for a Patient and closes for them later
- [ ] The priority score equals the additive weighted sum of the normalized severity (SOFA/24) and survival factors under the active weight profile, with each factor's contribution visible in the response
- [ ] The engine returns the ranked queue on demand, each entry carrying score, factor breakdown, active profile, and survival SHAP attributions from the injected adapter
- [ ] The survival adapter is an injectable seam; tests run against a deterministic fake
- [ ] A controllable clock lets tests advance time deterministically (used by later tickets)
- [ ] Tests exercise only external behaviour through the engine's public door — no internals