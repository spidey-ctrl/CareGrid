# 04 — Tie-Break Cascade

**What to build:** the end-to-end behaviour this ticket makes work: near-equal priority scores (equal after rounding to 2 decimals) resolve deterministically through the cascade — higher severity, then higher survival, then longer wait, then earlier Queue Entry creation — with each stage's reasoning surfaced on the tied rows so no near-equal ordering ever looks arbitrary.

**Blocked by:** 1 — Domain engine foundation; 2 — Waiting Time and re-ranking dynamics

**Status:** ready-for-agent

- [ ] Two entries whose scores are equal at 2 decimal places trigger the cascade; entries several decimals apart do not
- [ ] Cascades resolve in order: severity, then survival, then waiting time, then Queue Entry creation time
- [ ] The distinguishing stage and its reason are returned with the tied entries
- [ ] Re-running the identical queue yields an identical order (deterministic, replayable)