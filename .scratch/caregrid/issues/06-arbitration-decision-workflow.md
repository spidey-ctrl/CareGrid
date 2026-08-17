# 06 — Arbitration Decision workflow

**What to build:** the end-to-end behaviour this ticket makes work: when a bed frees up, the engine recommends the top-ranked Queue Entry with its full reasoning; the clinician confirms the allocation or consciously deviates to a lower-ranked entry; and the outcome — recommendation, confirmation, or deviation — lands as an Arbitration Decision in the same append-only trail as the snapshots, so every bed assignment is one contiguous, reviewable story.

**Blocked by:** 5 — Ranking Snapshots (audit trail)

**Status:** ready-for-agent

- [ ] Freeing a bed produces a recommendation for the current top-ranked entry, with its reasoning
- [ ] Confirming records the allocation and the allocated entry leaves the queue
- [ ] Deviating to a lower-ranked entry records the deviation distinctly — the clinician's choice always wins (ADR-0002)
- [ ] Both outcomes land in the same append-only trail as the snapshots
- [ ] No path auto-allocates a bed without the clinician's action