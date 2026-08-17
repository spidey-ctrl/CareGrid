# 07 — Dashboard

**What to build:** the end-to-end behaviour this ticket makes work: a read-only dashboard that renders the engine's queries and the snapshot trail — the live ranked queue with score and three factor bars, survival SHAP attributions, a one-line "why this rank" per row, a rank-movement indicator, the active weight-profile badge, inline tie-break reasoning, the event feed, and a replay slider that walks the audit trail through time.

**Blocked by:** 6 — Arbitration Decision workflow

**Status:** ready-for-agent

- [ ] Shows the live ranked queue with per-entry score, factor bars, SHAP attributions, profile badge, rank-movement indicator, and inline tie-break reasoning
- [ ] Shows the event feed and reflects every re-rank
- [ ] Replaying the audit trail renders the exact queue at any past snapshot
- [ ] The dashboard performs no decision logic of its own — it only reads engine outputs and snapshots