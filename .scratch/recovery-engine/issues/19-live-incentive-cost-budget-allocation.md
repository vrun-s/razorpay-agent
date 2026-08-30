# 19: Live incentive cost — make budget allocation actually bind

**What to build:** Thread a real, non-zero incentive cost through the live decision flow so `BudgetLedger.spent` moves and the Streaming Allocator's reserve mechanism has something to ration. The flat-incentive-response model per [[0014-flat-incentive-response-learnable-deferred]] — the learnable "discount-sensitivity" version is explicitly out of scope for this ticket.

**Blocked by:** 05, 06, 10, 15, 18 (reopens surface in all of them)

**Status:** ready-for-agent

## Construction sites (verified by grep 2026-08-30, not assumed)

`grep -n 'ProposedIntervention(|incentive_amount' backend/**/*.py`:

- **`app/lifecycle.py:148`** — `ProposedIntervention(intervention=intervention)` — the **only** construction site in the live decision flow. Ticket 17's real-Razorpay work added no second site. This is what gets the real `incentive_amount`.
- `app/evaluation.py:191` (baseline `no_intervention` arm, `NO_ACTION`) and `app/evaluation.py:248` (`fixed_rule` arm, already cost-bearing at `FIXED_RULE_DISCOUNT_PCT`) — two separate eval sites; leave the baseline at 0. The `ai_treatment` arm has no site of its own — it drives `lifecycle.py:148` through `run_simulated_case`, so fixing that one line is what makes `ai_treatment` cost-bearing.
- **Stale "always 0 / spent stays 0" assumptions to sweep:** `app/observability.py:53`, `app/evaluation.py:340`, `app/evaluation.py:403` (comments), `backend/tests/test_observability.py:45` (and the assertion it guards). These encode the old gap and will be wrong after this ticket.

## Scope

- [ ] New `MerchantConfig` object holds `recovery_budget` and `incentive_pct` (default `5.0`); `PolicyConfig.recovery_budget` and `BudgetLedger.recovery_budget` both derive from it — the two independently-configured copies flagged in `app/allocator.py` collapse to one.
- [ ] `app/lifecycle.py:148` computes `incentive_amount = round(case_value * incentive_pct)` for a `PAYMENT_RETRY` proposal and passes it into `ProposedIntervention` and the `AllocationCandidate`.
- [ ] Decision Engine proposes the incentive by a fixed rule — `INCENTIVE_UPLIFT > incentive_pct` — not a learned one. It stays greedy on intervention choice ([[0006-decision-engine-estimator]]); no `incentive` axis is added to `EstimatorCellKey`.
- [ ] `app/simulator/response_curves.py`: any executed intervention with `incentive_amount > 0` gets `+INCENTIVE_UPLIFT` (default `0.10`) added to its post-fatigue probability, clamped to `[_MIN_PROBABILITY, 1.0]`, uniform across all personas. Bump `SIMULATOR_VERSION` → `response-curves-v2`.
- [ ] Streaming Allocator gates the incentive spend only. When it declines to fund, the same intervention still executes with `incentive_amount = 0` (degrade to a free retry) — not `NO_ACTION`, not the current silent skip. Case History records the declined incentive distinctly from a funded one.
- [ ] **Do not conflate "allocator declined" with "no incentive was ever on the table."** A `PAYMENT_RETRY` where the engine proposed an incentive and the allocator said no is a *decline*; a proposal that structurally never had a cost (`incentive_amount` computed to 0 — every `RESUME_CHARGE` today, see below) is *not something the allocator was ever in the loop for*. Case History / the dashboard / the audit trail must show these as different facts. A subscription tab reading "declined" for every single case would misrepresent what happened.
- [ ] Evaluation: the `ai_treatment` arm carries the same case-value-scaled incentive cost as `fixed_rule` (both at `incentive_pct`). Only intervention choice and allocator funding differ between arms.
- [ ] `FAILED_PAYMENT` only. `HALTED_SUBSCRIPTION` `case_value` is `0` (no Plan-amount lookup) so `RESUME_CHARGE` `incentive_amount` computes to `0` for every case — meaning every `RESUME_CHARGE` proposal lands in the free branch and the allocator is never consulted for it. That's intentional (workflow excluded from the budget game), consistent with the eval harness's existing `FAILED_PAYMENT` default — but see the decline-vs-never-in-loop item above so it isn't logged as a stream of allocator declines.
- [ ] Regenerate `evaluation_report.json` (dev + held-out) under `response-curves-v2` and re-commit — the version bump invalidates the prior artifact.
- [ ] **Fastest did-it-work check, before looking at NRR deltas:** confirm `ai_treatment`'s total incentive spend in the regenerated report is no longer identically `0`. That zero was the concrete symptom that flagged the original gap; a non-zero value is the direct evidence the ticket landed.
- [ ] `BudgetTimeline.tsx`: drop the amber "no spend in the live flow" disclaimer; the Reserved Budget tab should now show real movement.

## Held-out set: mechanism update, not tuning (say this in the commit / PR message)

- [ ] Regenerating under `response-curves-v2` must **not** change the held-out set's composition — the 200 held-out cases (which cases, in what arrival order) come from `DEFAULT_DATASET_SEED` and the fixed sequential partition and stay byte-identical. Only the response-curve *function* that draws each case's outcome changes.
- [ ] That distinction is one sentence from looking like the thing [[0007-evaluation-integrity]] prohibits ("we changed the simulator and reran against held-out"). State explicitly in the commit/PR text: held-out case identities and order unchanged; this is a simulator-mechanism version bump with a full regenerate, not a tune against held-out results. If the regenerated held-out numbers are disappointing, they stand — do not adjust constants to improve them.

## Evaluation-integrity boundary (state this in the implementation, not just here)

- [ ] `INCENTIVE_UPLIFT` and `incentive_pct` are model constants — they apply identically to eval runs and the demo.
- [ ] The demo `recovery_budget` sizing and case-ordering are **walkthrough-only**: `app/demo_seed.py` sizes `recovery_budget` below total incentive demand and orders a low-`point_estimate` case before a high-`point_estimate` one so the allocator visibly declines-then-funds-better. The evaluation harness must not read that tuned budget or seed — it keeps the canonical `MerchantConfig` value and `DEFAULT_DATASET_SEED`, with its own fresh per-arm allocator instances as today. A demo knob reaching an eval run is a regression against [[0007-evaluation-integrity]].

## Out of scope (deferred to a possible follow-on ticket)

- Per-persona incentive-response curves and an `incentive` axis on `EstimatorCellKey` (the learnable "agent learned who's discount-sensitive" version). If attempted later, check per-cell observation counts on the 300-case dev split first; it would supersede part of [[0014-flat-incentive-response-learnable-deferred]].
- Plan-amount lookup to give `HALTED_SUBSCRIPTION` cases a non-zero `case_value`.

## Narrative guard

- [ ] The demo script / pitch must not claim the agent learns discount-sensitivity. Honest framing: budget pacing under a reserve — fund incentives where expected Net Recovered Revenue justifies the spend, hold the reserve for better arrivals the agent cannot foresee, decline mediocre cases rather than exhausting the budget early.

- [ ] All acceptance criteria verified, full backend suite + frontend build/lint green, `/code-review` run and findings addressed, changes committed before the next ticket.
