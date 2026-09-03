# Handoff — P1 evaluation spike ran, kill criteria FAILED, re-grill P1

**Date:** 2026-09-03
**Project:** Razorpay Revenue Recovery (Track 3, Buildathon 2026, solo build)
**This session:** ran the Phase 1 spike defined in
`docs/agent-handoffs/2026-09-03-01-handoff-p1-spike-and-rebuild-plan.md` as a
`/prototype`. All five changes hacked in, dev budget sweep run, kill criteria
checked. **Verdict: STOP — the AI arm does not separate from `fixed_rule`.**
**Next session:** take the root cause below into `/grill-with-docs` and rethink P1.
Do **not** start the Phase 2 clean build.

---

## Where everything is (do not re-derive)

- **Branch `prototype/p1-eval-spike`** — pushed to `origin`, **throwaway, never merge**.
  Breaks ~5 test modules by design (`test_decision`, `test_allocator`,
  `test_evaluation`, `test_policy`, simulator tests) — the spike skipped tests per
  its own scope.
  - `SPIKE_FINDINGS.md` (repo root on that branch) — **the full writeup**: the sweep
    table, all three failed kill criteria, the root-cause analysis, the list of
    every `# SPIKE (P1 eval)` edit. Read this first.
  - Commit `019c218` — the spike.
  - Runner: `cd backend && uv run python -m spike_p1_budget_sweep` (deterministic).
- **Prior handoff** `docs/agent-handoffs/2026-09-03-01-handoff-p1-spike-and-rebuild-plan.md`
  — the spike definition, Phase 2/3 plan, and the Q13–Q18 design decisions. Still
  the reference for everything except the spike verdict.
- Spike-independent docs already committed (`6e52f84`, branch
  `worktree-spike-independent-docs`): ADR-0013 amendment, CONTEXT Offline-Optimal edit.

## The result in one line

AI-arm NRR **trails** `fixed_rule` at every budget (₹2k/5k/10k/25k/50k on the 300-case
dev split): bootstrap gap point estimate −5.6k to −10.1k paise, CI upper bound only
just positive, AI recovers fewer cases and captures less of offline-optimal than the
blind fixed rule. Numbers table in `SPIKE_FINDINGS.md`.

## Root cause — this is the payload for the re-grill

1. **The estimator never observes failures.** `get_estimator().update(...)` is called
   **only ever with `success=True`** — `app/lifecycle.py:416` (`resolve_case_manually`)
   and `app/lifecycle.py:469` (`mark_recovered`), plus `app/demo_seed.py`. There is no
   `success=False` call anywhere. The Beta-Bernoulli posterior only accumulates α;
   β stays pinned at cold-start `2.0`. Every `payment_retry` cell inflates to
   `p̂ ≈ 0.86–0.96` regardless of the persona's true 0.20–0.55 odds.
   - This is why the *pre-spike* eval looked like a tie, not a loss: with
     `failure_reason` and `segment_proxy` both constant there is exactly one retry
     cell, it pegs near 1.0, `decide()` always retries → structurally identical to
     `fixed_rule`.
2. **Dispersing `failure_reason` then makes `decide()` worse, not better.** Once the
   axis varies, some `no_action` cells catch early lucky successes and climb past
   `payment_retry` cells for other `failure_reason` values. EV-max `decide()` starts
   choosing `NO_ACTION` on the strength of an inflated no-action `p̂`, skipping a
   retry that would have recovered the case.
3. **The streaming allocator's reserve gate is a non-lever in this regime.** Whole
   incentive demand (≤ ₹2.23M on cycle-1 across 300 cases) fits the non-reserved
   pool at every swept budget → 0 reserve draws, 0 declines observed. A gate can
   only decline, not re-queue: a "held" rupee is just unspent (AI strands ₹27.7k of
   a ₹50k budget; `fixed_rule` spends more and recovers more).
4. **Secondary, does not change the verdict:** the spike's budget-constrained
   offline-optimal arm is not a valid upper bound — greedy value-first 0/1 selection
   starves itself at tight budgets (offline NRR < both online arms at ₹2k). Needs a
   real knapsack when/if Phase 2 happens.

## What the next session should decide (in `/grill-with-docs`)

- **Fix the estimator online update rule first.** Feed `success=False` on terminal
  non-recovery (case reaches STOPPED, or the reassessment loop hits its cycle bound
  with no recovery). This is a prerequisite: without both Bernoulli outcomes no
  amount of cell dispersion produces a usable `p̂`, so the AI arm has no real edge
  to demonstrate and the whole P1 premise is moot. Likely needs its own ADR (amends
  ADR-0006's update rule) and touches `app/lifecycle.py`, `app/simulator_driver.py`
  (where terminal non-recovery is detected), maybe `app/estimator.py`.
- Only *after* that: re-ask whether per-cell `p̂` + allocator EV-gating actually
  separates the arms — and whether a streaming *gate* is even the right shape vs. a
  priced queue / dynamic threshold that spends the reserve.
- Re-confirm whether `failure_reason` should correlate with recoverability at all
  (the spike made it persona-conditioned; Q10 tuning discipline says pick the mix to
  look like plausible SME data, not to make AI win — revisit).
- Redesign offline-optimal as a genuine budget-constrained knapsack.
- Re-check the Phase 2 plan in the prior handoff against whatever the re-grill
  concludes — several of its 8 steps assume the spike passed.

## Housekeeping done this session

- Handoff doc: this file (also copied to the OS temp dir).
- The worktree `prototype+p1-eval-spike` is safe to delete — branch + findings are
  on `origin`. It was **not** merged/pushed to `master` (hard rule: never
  push/merge to master; and this is failing throwaway code regardless — the user
  does their own merges).

## Suggested skills for the next session

- **`/grill-with-docs`** — primary. Bring the estimator-never-sees-failures root
  cause and stress-test a revised P1 (fix the update rule → then re-evaluate the
  allocator lever).
- **`/domain-modeling`** — for the ADR amending ADR-0006's Beta-Bernoulli update
  rule to record failures.
- **`/prototype`** — only if the re-grill wants a second spike (e.g. "does the AI
  arm separate once the estimator sees failures?"); reuse branch
  `prototype/p1-eval-spike` as the starting point rather than redoing the plumbing.
- **`/to-spec` → `/to-tickets`** — deferred; only once a re-grilled P1 clears a
  kill-criteria check.
