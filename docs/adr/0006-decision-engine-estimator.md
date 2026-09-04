# Estimate recovery probability with a per-cell Bayesian model, not the LLM directly

`CONTEXT.md` defines Reassessment as "re-evaluating a case's recovery probability and economics," but nothing said how that probability is produced — and the whole net-recovery EV story depends on it being a defensible number, not a vibe. Three candidates existed: the LLM guesses the probability directly (fast, but "where does 27% come from?" has no answer and the number can't be calibrated); a learned/parametric estimator produces the number while the LLM handles context (defensible and calibratable, but needs a cold-start and a clear estimator design); or a rules table with the LLM only narrating (honest, but weak on "what is the AI actually doing?" for an AI Buildathon).

**Decision**: The probability comes from a Beta-Bernoulli posterior per `(failure_reason × customer_segment_proxy × intervention)` cell, updated online (`α += 1` on success, `β += 1` on failure) as cases resolve, starting from a flat `Beta(2,2)` cold-start prior. `customer_segment_proxy` ([[CONTEXT.md]]) is computed deterministically from observable Customer History fields (order count, AOV, payment-reliability rate) via fixed thresholds — not an LLM judgment call. The estimator updates only from the synthetic simulation stream; real Razorpay test-mode executions are excluded from the update stream entirely, because under the simulator↔Razorpay execution boundary ([[0007-evaluation-integrity]]) the simulator rolls the outcome first and a test harness only pays a real payment link when the simulator already decided that case recovers — so a real-executed outcome isn't independent evidence, it's a mechanical replay of a decision already counted. The LLM's role is fixed and never includes producing the probability itself: (1) diagnose `failure_reason` from unstructured decline text/bank codes, (2) generate the natural-language justification that goes into the audit trail, (3) flag escalation-worthy cases where the signal is qualitative. The streaming allocator ([[0003-streaming-allocation]]) consumes both the posterior's point estimate and an explicit uncertainty measure (e.g. credible interval width) — not the point estimate alone — so a sparse, shaky cell is naturally treated as riskier by the existing reserve-budget mechanism, rather than requiring a separate exploration algorithm (e.g. Thompson sampling).

**Consequences**: More to build than a stateless probability function — per-cell posterior storage, an online update path, source-tagging on every Case History entry (`simulated` vs `real`, even though only `simulated` feeds the estimator) — but the resulting number is calibratable (a predicted-vs-actual calibration curve becomes possible), the LLM has a real, bounded job a rules table couldn't do, and the allocator's decisions account for how much the system actually knows, not just what it currently believes.

---

**Amendment (2026-09-04) — the `β += 1 on failure` half of the update rule had no live caller.**
The decision above specifies the posterior is updated "`α += 1` on success, `β += 1` on failure."
Only the success half was ever wired: `mark_recovered` / `resolve_case_manually`
(`app/lifecycle.py`) call `estimator.update(..., success=True)` when a case reaches RECOVERED.
A resolved-but-unrecovered reassessment cycle in
`app/simulator_driver.py::run_simulated_case` simply looped or broke and discarded the
outcome, so no code path ever passed `success=False`. Every cell therefore accumulated only
`α`, and its `p̂` drifted toward 1.0 regardless of the persona's true odds — which is why the
pre-fix evaluation showed the AI arm tied to (not separated from) the flat-rule baseline.

The failure update is now wired at the same resolved-outcome point in `run_simulated_case`:
on `outcome.resolved and not outcome.recovered`, `resolve_last_decided_cell_key(case)`
attributes the failure to that cycle's own decision cell (a failed Payment Retry → the
retry cell; a `NO_ACTION` cycle with no spontaneous recovery → the no-action cell), recorded
**once per failed cycle** — the most Bernoulli trials, so the fastest posterior convergence.
This is a bug fix against the rule above, not a change to it. The exploration gap the
decision text punts to the allocator's uncertainty handling is unchanged and remains real
(the greedy `decide()` rarely samples `NO_ACTION`, so that cell stays sparse). Full analysis:
`docs/evaluation-findings-2026-09.md`.
