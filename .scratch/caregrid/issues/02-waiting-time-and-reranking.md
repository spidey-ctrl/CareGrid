# 02 — Waiting Time and re-ranking dynamics

**What to build:** the end-to-end behaviour this ticket makes work: waiting time accrues from a Queue Entry's creation and the queue re-ranks on every discrete event (new entry, removal, clinical update, weight-profile change, freed bed) plus a short scheduled recompute, so the ordering always reflects live scores as time and events move.

**Blocked by:** 1 — Domain engine foundation

**Status:** ready-for-agent

- [ ] Waiting Time accrues from a Queue Entry's creation and resets on a new Queue Entry for the same Patient
- [ ] The wait factor is the saturating quadratic `min(1,(t/T)²)` with a 24-hour horizon: effectively flat in the first hours, rising steeply, and capped at the horizon
- [ ] Every discrete event causes a re-rank before the next query returns
- [ ] A scheduled recompute (short, configurable interval) refreshes scores so slow wait drift never leaves a stale order
- [ ] After any sequence of events and time, the returned ranked queue is internally consistent: every score recomputed from live factors