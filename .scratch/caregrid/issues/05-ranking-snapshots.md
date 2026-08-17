# 05 — Ranking Snapshots (audit trail)

**What to build:** the end-to-end behaviour this ticket makes work: an immutable, append-only Ranking Snapshot is written on every re-rank, carrying the full ordered queue with each entry's score and factor breakdown, the survival term's SHAP attribution, the weight profile and wait horizon in effect, the trigger, and any tie-break reasoning — and a reviewer can retrieve the exact queue at any past re-rank, or a Patient's rank history, as a direct read.

**Blocked by:** 1 — Domain engine foundation; 2 — Waiting Time and re-ranking dynamics; 3 — Weight Profiles; 4 — Tie-Break Cascade

**Status:** ready-for-agent

- [ ] Every re-rank appends a snapshot in creation order
- [ ] Each snapshot contains: ordered queue, per-entry score + factor breakdown, survival SHAP attribution, weight profile, wait horizon, trigger, and tie-break reasoning
- [ ] The trail is append-only — there is no edit or delete operation
- [ ] A reviewer can retrieve the exact queue at any past re-rank from the stored record without replaying events
- [ ] A Patient's rank history across snapshots is queryable