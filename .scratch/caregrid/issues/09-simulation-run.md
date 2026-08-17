# 09 — Simulation Run + gating

**What to build:** the end-to-end behaviour this ticket makes work: a scenario generator that produces a realistic ICU-style queue with deliberately loaded edge cases (near-ties, an exhausted long-waiter, an arrival that tips a tie), plays events through the engine under a chosen weight profile, honours the validation gate, and yields the Ranking Snapshot trail that demonstrates the arbitration logic end-to-end.

**Blocked by:** 6 — Arbitration Decision workflow; 8 — Survival model harness + validation gate

**Status:** resolved (implemented Aug 18 2026)

- [x] Generates a scenario that deterministically includes the loaded edge cases: near-ties, an exhausted long-waiter, and a tipping arrival
- [x] Plays arrivals, removals, and a freed bed through the engine under a selected weight profile
- [x] Produces the snapshot trail a reviewer can replay end-to-end
- [x] Honours the validation gate from ticket 8 — no demonstration when the model fails
- [x] Runnable under all three weight profiles for comparison