---
Status: accepted
---

# The evaluation harness runs every arm with the Reserved Budget switched off

Once the online failure update is wired ([[0006-decision-engine-estimator]], amendment note),
the evaluation harness's estimator converges to a *truthful* per-cell recovery
probability instead of one pinned near 1.0. That exposes a second problem, upstream of
any headline number.

The harness's estimator has exactly **one** non-trivial cell. `_failed_payment_payload`
(`app/simulator_driver.py`) hardcodes `"insufficient funds in account"`, which
`FakeLLMClient` diagnoses as `insufficient_funds` for every case;
`_customer_history_from_payment` (`app/lifecycle.py`) hardcodes `order_count=1`, which
`customer_segment_proxy` buckets as `NEW` for every case. So the only cells that ever see
traffic are `(insufficient_funds, new, payment_retry)` and `(insufficient_funds, new, no_action)`.

A calibrated `payment_retry` cell converges to a population-blended, fatigue-dragged
`p̂` that sits **below 0.5** (`app/simulator/response_curves.py`: per-persona cycle-1
retry rates 0.20–0.55, dragged down by `FATIGUE_DECAY_RATE` across repeats). The
Streaming Allocator's reserve-quality gate (`app/allocator.py`) requires
`p̂ − uncertainty/2 ≥ _DEFAULT_MIN_QUALITY_SCORE` (0.5) before an incentive may draw
against the reserved third. A truthful `p̂ ≈ 0.4` never clears that bar — so once the AI
arm has spent its non-reserved 2/3, every further AI incentive is declined and the
reserved third is **stranded**. `fixed_rule` feeds the allocator a hardcoded
`point_estimate=0.5, uncertainty=0.0` ([[0013-evaluation-metric-baselines-contract]]:
"no Decision Engine estimate involved"), clears `0.5 ≥ 0.5`, and spends its whole budget.
A *truthful* estimator therefore uniquely handicaps the AI arm through a gate the blind
baseline sails past. With a single estimator cell there is no cross-case quality signal
to ration a reserve on in the first place: the mechanism can only mis-fire here, not add
information.

**Decision**: the evaluation harness builds every arm's `StreamingAllocator` with
`reserve_ratio = 0.0`, via a single module constant `_EVAL_RESERVE_RATIO` in
`app/evaluation.py` referenced by `run_no_intervention_arm`, `run_fixed_rule_arm`, and
`run_ai_treatment_arm`. Budget is first-come-first-served for every arm; `p̂` never gates
funding in evaluation. The value is `0.0` on principle (there is nothing to ration on),
not tuned toward any arm's result — the frozen/set-once/tunable discipline from the
2026-09-03 grill still governs, and no parameter here is chosen by "does the AI win".

- `run_no_intervention_arm` is inert under this change (its proposal always costs 0, so
  it is funded on the non-reserved path regardless) — converted for uniformity, not effect.
- `run_offline_optimal_arm` has no allocator at all and is untouched.
- `app/allocator.py::_DEFAULT_RESERVE_RATIO = 1/3` is **unchanged**. Every live and demo
  path still reserves a third; `app/demo_seed.py` still exercises the reserve mechanism
  end to end (disclosed as demo-only).

**Consequences**:

- **The evaluation no longer exercises the Reserved Budget.** `CONTEXT.md`'s
  **Reserved Budget** entry describes a mechanism the allocator applies on every online
  path; after this ADR the harness is an exception to that, and the reserve's behaviour
  is evaluated only in the demo seed, not measured. The `CONTEXT.md` entry carries a
  one-line pointer here. The absolute quality bar being an anti-lever for a calibrated
  estimator — and the case for a relative / opportunity-cost reserve gate instead — is
  written up as Finding 1 in `docs/evaluation-findings-2026-09.md`; that redesign is
  deferred past the 2026-09-05 submission.
- **This is a symmetry restoration, not a new confound.** [[0013-evaluation-metric-baselines-contract]]
  requires the allocator to be structurally identical across arms. The pre-existing
  asymmetry was `fixed_rule`'s hardcoded `0.5` clearing a gate the AI arm's truthful
  `p̂` could not; zeroing the reserve for all arms removes it. The AI arm's entire
  structural edge remains its real per-cell `p̂` versus the baseline's flat prior.
- **"% of Offline-Optimal captured" is unaffected.** That fairness argument
  (`CONTEXT.md`: Offline-Optimal Allocation) rests on equal *budgets* and *attempt
  ceilings* across arms, both still equal here — not on the reserve, which
  Offline-Optimal never withheld anyway.
- **A future multi-cell harness must revisit this.** If per-case `failure_reason` /
  `customer_segment_proxy` dispersion is ever added (a frozen-simulator change, out of
  scope now), a real quality signal returns and the reserve becomes evaluable again —
  at which point `_EVAL_RESERVE_RATIO` should be reconsidered alongside the reserve-gate
  redesign, not silently kept at 0.
