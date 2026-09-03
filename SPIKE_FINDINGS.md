# P1 evaluation spike — result

**Branch:** `prototype/p1-eval-spike` (throwaway, do not merge)
**Date:** 2026-09-03
**Question (from `docs/agent-handoffs/2026-09-03-01-...`):** does the AI arm separate
from `fixed_rule` on NRR once the recovery budget binds, given per-case value +
failure-reason dispersion, EV-maximising `decide()`, and EV/reserve allocator gates?

## Verdict: **NO — STOP. Back to `/grill-with-docs` to rethink P1.**

All three kill criteria fail. The AI arm **trails** `fixed_rule` at every budget level.

### Dev split (300 cases), budget sweep

| budget | AI NRR | fixed NRR | offline NRR | AI−fixed gap | 95% CI | AI %opt | fix %opt | AI rec | fix rec | AI spend | fix spend |
|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| ₹2k  | 33,742,273 | 35,422,147 | 26,503,684 | −5,600 | [−16,668, 1,801] | 127.3% | 133.6% | 197 | 202 | 199,993 | 199,807 |
| ₹5k  | 33,697,680 | 36,741,237 | 32,204,293 | −10,145 | [−24,147, 336] | 104.6% | 114.1% | 199 | 205 | 499,992 | 499,784 |
| ₹10k | 33,761,806 | 36,783,626 | 37,632,020 | −10,073 | [−24,178, 426] | 89.7% | 97.7% | 202 | 208 | 999,971 | 999,969 |
| ₹25k | 33,077,450 | 35,917,955 | 37,632,020 | −9,468 | [−23,190, 698] | 87.9% | 95.4% | 211 | 218 | 2,227,110 | 2,499,712 |
| ₹50k | 33,077,450 | 35,833,443 | 37,632,020 | −9,187 | [−22,918, 990] | 87.9% | 95.2% | 211 | 218 | 2,227,110 | 2,584,224 |

(NRR / spend in paise. `run_seed = DEFAULT_DATASET_SEED`, 10k bootstrap resamples.)

- Gap point estimate is **negative at every budget**; CI upper bound is only barely
  positive (~300–1,800), i.e. "AI ≈ fixed_rule, leaning slightly worse."
- AI recovers **fewer** cases than the blind fixed rule at every level.
- AI's %-of-offline-optimal is **below** fixed_rule's at every level.

## Root cause (this is the payload for the re-grill)

### 1. The estimator never observes failures — every `p̂` inflates toward 1.0

`estimator.update(...)` is called **only ever with `success=True`** (`lifecycle.py:416`,
`:469`; `demo_seed.py`). There is no `success=False` update anywhere in the codebase.
The Beta-Bernoulli posterior only accumulates α; β stays at the cold-start `2.0`
forever. So after warmup every `payment_retry` cell reads `p̂ ≈ 0.86–0.96` regardless
of the persona's true recovery odds (0.20–0.55):

```
insufficient_funds   new  payment_retry  p_hat=0.959  n=45
customer_cancelled   new  no_action      p_hat=0.833  n=8     <- true no-action odds ~0.05-0.15
expired_card         new  payment_retry  p_hat=0.957  n=43
fraud_suspected      new  payment_retry  p_hat=0.882  n=13
```

This is masked in the pre-spike eval: with `failure_reason` and `segment_proxy` both
constant there's one retry cell + one no-action cell, both climb to ~1.0, retry wins
on tie-order, the arm always retries — identical to `fixed_rule`, hence the "tie."

### 2. Dispersing `failure_reason` makes EV-`decide()` actively worse

Once `failure_reason` varies, a few no-action cells catch early lucky successes and
climb past retry cells for *other* categories. EV-max `decide()` then picks
`NO_ACTION` for those cases on the strength of an inflated no-action `p̂` — skipping
a retry that would have recovered the case. The AI arm's per-cell estimates make it
*mis-rank interventions*, where the blind fixed rule just always retries.

### 3. The allocator's reserve gate is a non-lever here

The mechanism the handoff hoped for ("AI reserves budget for high-`p̂` cases arriving
later") never fires: at every budget the whole incentive demand (≤ ₹2.23M on cycle-1
across 300 cases) fits in the non-reserved pool, so **0 reserve draws, 0 declines**.
The streaming allocator can only gate, not prioritise — a "held" rupee isn't
redirected to a better case, it's just unspent. At ₹50k, AI strands ₹27.7k of its
₹50k budget while `fixed_rule` spends ₹25.8k.

### 4. Secondary: the spike's offline arm is not a valid upper bound

Greedy value-first 0/1 selection under a tight budget starves itself (funds ~7 huge
cases, skips hundreds of cheap recoverable ones): offline NRR at ₹2k (26.5M) is
*below* both online arms. Needs a real knapsack in Phase 2. Does not affect the
verdict — criteria 1 & 2 fail on the gap/CI alone.

## Recommended next step

Take to `/grill-with-docs`:
- **Fix the estimator's online update rule first** — feed `success=False` on terminal
  non-recovery (case STOPPED / max cycles reached with no recovery). Without both
  outcomes, no amount of cell dispersion yields a usable `p̂` and the AI arm has no
  real edge to demonstrate.
- Then re-ask whether the allocator EV-gating lever separates the arms — and whether
  a streaming *gate* is even the right shape, vs. a priced queue / threshold that
  actually spends the reserve.
- Redesign the offline-optimal arm as a genuine budget-constrained knapsack.

## Spike changes (all marked `# SPIKE (P1 eval)`)

- `simulator/generator.py` — per-case lognormal `case_value` + persona-conditioned
  `failure_reason` + matching decline text on `SimulatedCase`.
- `simulator_driver.py` — `_failed_payment_payload` emits per-case amount + decline
  text; `run_simulated_case` threads a `policy` (swept budget).
- `intake.py` — `create_case_from_failed_payment` forwards `policy`.
- `decision.py` — `DecisionInput.case_value`; `decide()` maximises `p̂·value − incentive`.
- `lifecycle.py` — `case_value` into `DecisionInput`; `expected_net_value` onto the
  `AllocationCandidate`.
- `allocator.py` — `point_estimate: float | None`, `expected_net_value` field,
  EV-margin gate on the available pool, both gates skipped when `point_estimate is None`.
- `evaluation.py` — all arms use per-case `case_value`; `fixed_rule`/`no_intervention`
  pass `point_estimate=None` and share one allocator; `run_evaluation(recovery_budget=)`
  sweep param; `run_offline_optimal_arm` rewritten as a (flawed, see §4) budget-
  constrained greedy arm.
- `spike_p1_budget_sweep.py` — the runner + kill-criteria check.

Reproduce: `cd backend && uv run python -m spike_p1_budget_sweep`
