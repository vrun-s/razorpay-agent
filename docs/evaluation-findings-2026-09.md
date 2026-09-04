# Evaluation findings — September 2026

This project's headline metric is a paired counterfactual replay (ADR-0013): the same
synthetic case stream, one RNG seed, run through four arms — `no_intervention`,
`fixed_rule` (flat 5% discount on every case), `ai_treatment` (the real engine), and
`offline_optimal` (retrospective, full hindsight). The comparison that matters is the AI
arm's per-case Net Recovered Revenue (NRR) gap against each baseline, with a
10,000-resample bootstrap CI.

Building that evaluation surfaced two design limits **in our own agent**. Both are
documented here rather than papered over; one is fixed, one is accepted and explained.

## The result

`failed_payment` workflow, dataset seed `20260826`, canonical `DEFAULT_MERCHANT_CONFIG`
budget. Held-out is touched exactly once (ADR-0007).

### Held-out split (200 cases) — the headline

| Arm | Recovered | Incentive spend | NRR |
|---|---:|---:|---:|
| No intervention | 35 / 200 | ₹0 | ₹17,500 |
| Fixed rule (flat 5%) | 144 / 200 | ₹9,025 | ₹62,975 |
| **AI treatment** | **129 / 200** | **₹4,900** | **₹59,600** |
| Offline-optimal (hindsight) | 139 / 200 | ₹0 | ₹69,500 |

- **vs no intervention:** +₹210.50 per case, 95% CI **[+₹175.63, +₹245.38]** — excludes
  zero. The learned policy beats doing nothing decisively (+₹42,100 across the split).
- **vs the flat-5% fixed rule:** −₹16.88 per case, 95% CI **[−₹36.13, +₹0.00]** — the
  interval's upper bound sits at zero. On NRR the AI is statistically indistinguishable
  from, to marginally behind, a blanket discount here — while spending **~46% less
  incentive budget** (₹4,900 vs ₹9,025) for ~90% of the recoveries.
- **% of offline-optimal captured:** 85.8%.

### Dev split (300 cases) — same picture

| Arm | Recovered | NRR |
|---|---:|---:|
| No intervention | 54 / 300 | ₹27,000 |
| Fixed rule | 225 / 300 | ₹98,700 |
| AI treatment | 209 / 300 | ₹97,000 |
| Offline-optimal | 220 / 300 | ₹110,000 |

vs fixed rule: −₹5.67 per case, CI [−₹19.00, +₹6.17] (straddles zero). vs no
intervention: +₹233.33 per case, CI [+₹205.00, +₹261.67]. % of offline-optimal: 88.2%.

**Pre-committed reading (2026-09-03 grill, Q1):** honest measurement only, no parameter
chosen by "does the AI win." The headline is: *learned per-cell allocation matches but
does not beat a well-tuned flat rule under a flat incentive; it decisively beats no
intervention and captures ~86% of the foresight ceiling at roughly half the incentive
spend of the flat rule.* The two findings below explain why it doesn't pull ahead on NRR.

## Finding 1 — the reserve mechanism can't be measured with a single estimator cell

**Mechanism.** The evaluation harness's estimator collapses to one non-trivial cell.
`_failed_payment_payload` (`app/simulator_driver.py`) hardcodes `"insufficient funds in
account"`, which `FakeLLMClient` diagnoses as `insufficient_funds` for every case;
`_customer_history_from_payment` (`app/lifecycle.py`) hardcodes `order_count=1`, which
`customer_segment_proxy` buckets as `NEW` for every case. So the only cells that ever see
traffic are `(insufficient_funds, new, payment_retry)` and `(insufficient_funds, new,
no_action)`.

Once the online failure update is wired (Finding-3 fix below), the `payment_retry` cell
converges to a **truthful** population-blended, fatigue-dragged `p̂` — 0.34 on held-out
(α=128, β=251), 0.37 on dev (α=211, β=353). Both sit **below 0.5**.

The Streaming Allocator's reserve-quality gate (`app/allocator.py`) requires
`p̂ − uncertainty/2 ≥ 0.5` before an incentive may draw against the reserved third. A
truthful `p̂ ≈ 0.35` never clears that bar. So once the AI arm has spent its non-reserved
2/3, every further AI incentive is declined and the reserved third is **stranded**.
`fixed_rule` feeds the allocator a hardcoded `point_estimate=0.5` (ADR-0013: "no Decision
Engine estimate involved"), clears `0.5 ≥ 0.5`, and spends its whole budget. A *truthful*
estimator uniquely handicaps the AI arm through a gate the blind baseline sails past — and
with a single cell there is no cross-case quality signal to ration a reserve on in the
first place.

**Fix (shipped): [ADR-0016](adr/0016-evaluation-harness-runs-without-reserve.md).** The
evaluation harness builds every arm's allocator with `reserve_ratio = 0.0`
(`_EVAL_RESERVE_RATIO` in `app/evaluation.py`). Budget is first-come-first-served for
every arm; `p̂` never gates funding in evaluation. This *restores* symmetry rather than
adding a confound — it removes the pre-existing asymmetry where `fixed_rule`'s hardcoded
0.5 cleared a gate the AI arm's real `p̂` could not. `app/allocator.py`'s live/demo
`_DEFAULT_RESERVE_RATIO = 1/3` is untouched; `demo_seed.py` still exercises the reserve
end to end.

**Deferred (post-submission).** The reserve mechanism is now evaluated only in the demo
seed, not measured. The real fix is a **relative / opportunity-cost reserve gate** (fund
if this candidate beats the running distribution of arrivals, not an absolute 0.5 bar),
which would also make the reserve evaluable again — but only once the estimator has more
than one cell to compare across. That needs per-case `failure_reason` /
`customer_segment_proxy` dispersion in the simulator, a frozen-simulator change with a
`SIMULATOR_VERSION` bump and a held-out regeneration — out of scope two days before the
deadline.

## Finding 2 — greedy `decide()` leaves the no-action cell near its prior, and oscillates

**Mechanism.** `decide()` (`app/decision.py`) is greedy: it proposes whichever
intervention has the higher point estimate. From the Beta(2,2) cold start,
`VALID_INTERVENTIONS` tie-order makes it propose `PAYMENT_RETRY` first, and the frozen
response curves (`app/simulator/response_curves.py`) have retry dominating no-action for
every persona, so it keeps proposing retry. The **no-action cell is therefore rarely
updated** and sits near its 0.5 prior far longer than the retry cell (held-out: no-action
α=5, β=24 after ~25 trials vs retry's ~375; dev: α=2, β=6 after ~4 trials).

Once the truthfully-estimated retry cell dips below 0.5 while the no-action cell is still
near its prior, `decide()` flips to `NO_ACTION` for a stretch of cases — which then
recover only at the ~0.18 spontaneous rate instead of ~0.35 — until the no-action cell
collects enough failures to drop back below the retry cell and `decide()` flips back. A
transient `NO_ACTION` window mid-run, costing recoveries. This is exactly the exploration
gap ADR-0006 punts to the allocator's uncertainty handling; the allocator does not fill
it either.

**Accepted, not fixed.** The gap in the held-out AI-vs-`fixed_rule` result is
mechanically attributable to this window. The fixes — a non-greedy `decide()` (Thompson
sampling / UCB), or widening the Beta prior — are parameter changes to a scored system
two days before submission, which invites exactly the "tuned to win" suspicion ADR-0007
exists to prevent. Reported as-is (Q1). It is the deferred "(c)" work alongside the
reserve-gate redesign.

## Finding 3 (root cause, fixed) — the failure half of the update rule was dead code

ADR-0006 specifies the posterior updates "`α += 1` on success, `β += 1` on failure."
Only the success half was ever wired. A resolved-but-unrecovered reassessment cycle in
`app/simulator_driver.py::run_simulated_case` discarded its outcome, so `β` stayed pinned
at the cold-start 2.0 and every cell's `p̂` inflated toward 1.0. This is why the *pre-fix*
evaluation looked like a tie rather than a loss: with `failure_reason` and `segment_proxy`
both constant, the single retry cell pegged near 1.0 and `decide()` always retried —
structurally identical to `fixed_rule`.

Now wired at the resolved-outcome point in `run_simulated_case`
(`get_estimator().update(resolve_last_decided_cell_key(case), source=case.source,
success=False)` on `outcome.resolved and not outcome.recovered`), recorded once per failed
cycle. Dated amendment note in
[ADR-0006](adr/0006-decision-engine-estimator.md). This is what makes the calibration
curve meaningful: held-out, predicted vs observed is 0.335 vs 0.332 in the populated
bucket (n=322).

## Also noted — offline-optimal is an unconstrained reference

`run_offline_optimal_arm` charges zero Incentive cost and ignores the Recovery Budget (it
has no Policy Engine or allocator in the loop), so its NRR is gross-recovered with no
incentive deduction. "% of offline-optimal captured" is therefore a loose reference, not
the constrained ceiling `CONTEXT.md` describes. A budget-constrained knapsack is deferred.
(This is why offline-optimal can show *fewer* recoveries than `fixed_rule` yet higher
NRR.)

## Reproduce

```bash
cd backend
uv run python -m app.evaluation --split dev        # writes evaluation_report.json (dashboard)
uv run python -m app.evaluation --split held_out --out evaluation_report_held_out.json
```

Deterministic — both reproduce their committed files byte-for-byte. The estimator
convergence figures above come from a one-off dump of `get_estimator()._cells` after the
AI arm; not part of the committed artifact.
