# 03 — Weight Profiles

**What to build:** the end-to-end behaviour this ticket makes work: the three named presets — Severity-dominant (50/30/20), Balanced (40/30/30), Severity-heavy (60/25/15) — are selectable as the profile for a run, every existing and future score recomputes under the active profile, and the active profile rides along on every ranking query so the same queue can be compared across profiles.

**Blocked by:** 1 — Domain engine foundation; 2 — Waiting Time and re-ranking dynamics

**Status:** ready-for-agent

- [ ] The three named profiles exist with exactly the specified weight splits
- [ ] Selecting a profile changes the score of every Queue Entry, including ones already ranked
- [ ] The active profile is returned with every ranked-queue query
- [ ] The same queue scored under each profile produces orderings that match the profile's intent (e.g. Severity-dominant ranks the most severe highest)