# Handoff — P1 evaluation fix: re-grill concluded, plan ready to execute

**Date:** 2026-09-03
**Project:** Razorpay Revenue Recovery (Track 3, Buildathon 2026, solo build)
**Deadline:** 2026-09-05
**This session:** a `/grill-with-docs` session that took the failed spike's root cause
(`docs/agent-handoffs/2026-09-03-02-handoff-p1-spike-result.md`) through a full design
tree. Reached complete shared understanding, all decisions confirmed by the user.
**No code was written and no worktree was entered.**
**Next session:** execute the plan below. Start with a worktree + branch off `master`.

---

## Status of the three prior docs

- `docs/agent-handoffs/2026-09-03-01-handoff-p1-spike-and-rebuild-plan.md` — its **Phase 1
  spike is done and failed**; its **Phase 2 clean-build plan is now superseded** by this
  doc (several of its 8 steps assumed the spike passed). Its Phase 0 (P2a manual Razorpay
  txn) and Phase 3 ordering still stand. Its "Key facts discovered" section is still
  accurate and worth reading to avoid re-deriving.
- `docs/agent-handoffs/2026-09-03-02-handoff-p1-spike-result.md` + `SPIKE_FINDINGS.md`
  (repo root on branch `prototype/p1-eval-spike`, commit `019c218`) — the spike verdict.
  This session is the `/grill-with-docs` re-grill that doc asked for. The spike branch
  stays throwaway; **do not** build on it (its `case_value` / EV `decide()` /
  `point_estimate: float | None` work is all out of scope now — see "Not doing" below).
- Spike-independent docs already committed (`6e52f84`, branch
  `worktree-spike-independent-docs`): ADR-0013 amendment, CONTEXT Offline-Optimal edit.

---

## The two findings (this is the analytical payload — nowhere else yet)

Both were derived and verified against the code this session. Root cause #1 from the spike
result (estimator never sees failures) is confirmed; findings 1 and 2 below are the
*consequences of fixing it* under the current single-cell evaluation.

### Context verified against code

- `estimator.update(...)` is called in exactly 3 places — `lifecycle.py:414`,
  `lifecycle.py:467`, `demo_seed.py` — all `success=True`. The `success=False` branch
  (`cell.beta += 1`, `estimator.py:122`) is specified in ADR-0006 ("`β += 1` on failure")
  but **no production caller reaches it**. In `simulator_driver.py::run_simulated_case`
  terminal non-recovery just `break`s; every resolved-but-failed cycle outcome is
  discarded.
- **The eval harness estimator has exactly two cells.** `_customer_history_from_payment`
  (`lifecycle.py:95`) hardcodes `order_count=1` → `customer_segment_proxy` always returns
  `NEW`. `_failed_payment_payload` (`simulator_driver.py:71`) hardcodes
  `"insufficient funds in account"` → `FakeLLMClient` diagnoses `insufficient_funds` for
  every case. So the only cells are `(insufficient_funds, new, payment_retry)` and
  `(insufficient_funds, new, no_action)`.
- **Retry dominates no-action for every persona** (`response_curves.py`
  `BASE_RESPONSE_CURVES`): LOYAL 0.55/0.35, BARGAIN_HUNTER 0.45/0.10, NEW 0.35/0.15,
  UNRELIABLE_PAYER 0.20/0.05. Min margin +0.15. Caveat: `FATIGUE_DECAY_RATE=0.65` per
  repeat; UNRELIABLE_PAYER retry after ~3 priors ≈ 0.055 ≈ its no-action rate. The
  estimator has no attempt-count axis, so its retry cell converges to the
  attempt-mix-weighted rate, not the cycle-1 rate.
- `resolve_last_decided_cell_key` (`decision.py:69`) correctly attributes a failed
  `NO_ACTION` cycle: `run_decision_cycle` logs a DECISION entry every cycle
  (`lifecycle.py:171`) with `intervention` / `failure_reason` / `customer_segment_proxy`
  always populated; the function's hard `data[...]` subscripts never KeyError. A
  policy-rejected (never-executed) final decision does not get a spurious β because
  `_resolve_cycle_outcome` returns `resolved=False` when nothing executed and the case is
  no longer OPEN.

### Finding 1 — the reserve mechanism cannot be evaluated with a single estimator cell

A calibrated estimator converges the retry cell to `p̂ ≈ 0.40` (population-blended,
fatigue-dragged). The Streaming Allocator's reserve-quality gate (`allocator.py:126`)
needs `p̂ − uncertainty/2 ≥ 0.5` (`_DEFAULT_MIN_QUALITY_SCORE`) to draw against the
reserved third. A truthful `p̂ ≈ 0.40` **never clears 0.5**, so once the AI arm's
non-reserved 2/3 pool is spent, every further AI incentive is declined and the reserve is
**stranded**. `fixed_rule` feeds a hardcoded `point_estimate=0.5, uncertainty=0.0` →
`0.5 ≥ 0.5` is true → it spends its whole budget. So a *truthful* estimator uniquely
handicaps the AI arm through a gate the blind baseline sails through. The absolute quality
bar is an **anti-lever** for a calibrated estimator. Real fix = a relative /
opportunity-cost reserve gate; that is post-submission work (the deferred "(c)" — see
below).

### Finding 2 — greedy `decide()` + cold-start Beta(2,2) oscillation

Greedy `decide()` (`decision.py:89`) almost never proposes `NO_ACTION` (retry dominates
from cold start via `VALID_INTERVENTIONS` tie-order), so **the no-action cell is rarely
updated and sits near its Beta(2,2) = 0.5 prior**. Once the truthfully-estimated retry
cell dips below 0.5, `decide()` flips to `NO_ACTION` for a stretch of cases — which then
recover at the ~0.18 spontaneous rate instead of ~0.40, under-performing `fixed_rule` —
until the no-action cell collects enough failures to drop back below the retry cell and
`decide()` flips back. A transient `NO_ACTION` window mid-run, costing recoveries. This is
the exploration gap ADR-0006 explicitly punted to the allocator, which the allocator does
not fill either. Accepted and documented, **not fixed** (changing the prior two days out
invites tuning-suspicion; that is the deferred "(c)" work).

### Predicted Sept 5 result

AI tracks `fixed_rule` closely except during the Finding-2 oscillation window, where it
under-recovers. **Headline: AI trails `fixed_rule` by a modest margin, bootstrap CI
straddling 0 or slightly negative**, gap mechanically attributable to the oscillation.
Sign is knife-edge — depends whether the +0.10 `INCENTIVE_UPLIFT` keeps the realized
retry rate ≥ 0.5 for the whole run. Reported **as-is**, whatever held-out says. Per Q1
(below) this is an accepted outcome, not a failure.

---

## Design decisions from the grill (rationale, since it is nowhere else)

- **Q1 — honest measurement only.** No engineered win (circularity two days before
  submission is the worst possible trade). No parameter is ever chosen by "does AI win"
  (the prior handoff's Q10 tuning-discipline table still governs). Pre-committed: if
  held-out shows AI ≤ `fixed_rule`, that *is* the headline and the demo narrative shifts
  to "when does learned allocation beat a flat rule, and when doesn't it."
- **Q2 — mechanism of the AI's edge, accepted.** Under flat incentive (ADR-0014) + the
  frozen curves (retry dominates no-action for all personas), greedy `decide()` proposes
  the *same intervention* as `fixed_rule` on nearly every cycle-1 case. The AI can only
  differ by (i) stopping retries earlier on learned-low-odds cells and (ii) the allocator
  declining low-quality incentives so budget survives for better later arrivals. Both need
  ALL of: estimator sees failures **and** a discriminating axis; budget genuinely binds;
  declined budget actually redeployed. The four are jointly necessary and the edge is thin
  by construction under ADR-0014. **5th precondition** (user-added): cells must accumulate
  enough samples early enough to leave the Beta(2,2) prior before that cell's arrivals dry
  up — non-issue for the two-cell eval, becomes real only if axes are dispersed.
- **Q4 — Scope A only.** Estimator failure-update + one allocator constant. No
  simulator/driver change.
- **Q5 — (e): `_EVAL_RESERVE_RATIO = 0.0`** across the three eval arm builders. The
  single-cell eval has no quality signal to ration on, so budget is first-come-first-served
  equally for every arm; `p̂` never gates funding. Not tuned to outcome. The reserve
  mechanism stays exercised in `demo_seed.py` (disclosed as demo-only).
  `allocator.py::_DEFAULT_RESERVE_RATIO = 1/3` is **untouched** — live/demo paths still
  reserve a third.
- **Q6 — (i): failure recorded per resolved-but-failed cycle**, not terminal-only.
  Symmetric with how success is already observed; most Bernoulli trials → fastest
  convergence; correct attribution (a failed retry hits the retry cell). **No new ADR** —
  it is a bug fix against ADR-0006's existing spec; add a dated amendment note to
  ADR-0006.
- **Q7 — (b): headline is the two bootstrap CIs** (AI vs `no_intervention`, AI vs
  `fixed_rule`) — which ADR-0013 already calls *the* headline. Leave
  `run_offline_optimal_arm` as-is (costs 0, guaranteed 10 attempts); add a caveat line +
  an implementation-gap note reconciling it with the CONTEXT.md Offline-Optimal entry
  (updated in `6e52f84` to describe a constrained version the code does not implement).
- **Q9 — (a): accept the Finding-2 oscillation**, document it. No `decide()` or prior
  change.
- **Q10 — ship** (not docs-only). Go/no-go: the test suite. If `test_estimator` /
  `test_evaluation` / `test_lifecycle` updates run past ~½ day (end of Sept 3), fall back
  to docs-only against current code rather than ship a red suite.
- **Q11 — held-out discipline.** Regenerate `evaluation_report.json` (dev split) freely
  during dev; one `run_evaluation` on `held_out` at the canonical
  `DEFAULT_MERCHANT_CONFIG` budget, run once after code + dev numbers are frozen; that is
  the README headline. If held-out is *qualitatively* different from dev, report as-is —
  do not go back and touch code.
- **Q12 — docs.** README `## Documented findings` section (tight, both mechanisms,
  mechanism-before-numbers) linking to `docs/evaluation-findings-2026-09.md` (full
  analysis). New `docs/adr/0016-evaluation-harness-runs-without-reserve.md`. ADR-0006 gets
  only a dated amendment note (bug fix, not a decision).
- **Q13 — (c): control the narrative.** Dashboard eval panel gets a one-line pointer to
  the findings; demo video script gets two sentences owning both findings ("our evaluation
  caught two design limits in our own agent — here they are").
- **Deferred "(c)" work (post Sept 5):** relative/opportunity-cost reserve gate; the
  `decide()` exploration gap; per-case `case_value` + real `failure_reason` dispersion
  (needs a frozen-simulator change, `SIMULATOR_VERSION` bump, held-out regeneration);
  possibly reopening ADR-0014 for learnable discount-sensitivity.

---

## Course of action — execute in this order

Branch off `master` in a fresh worktree. Concise commits (user preference). Never
merge/push to `master` — the user does their own merges.

1. **Worktree + branch.** Record the baseline `cd backend && uv run pytest` pass count.
2. **Change 1 — wire the failure update.** In
   `backend/app/simulator_driver.py::run_simulated_case`, at the
   `outcome.resolved and not outcome.recovered` branch (covers a failed executed
   intervention *and* a resolved-but-unrecovered `NO_ACTION`), call
   `get_estimator().update(resolve_last_decided_cell_key(case), source=case.source, success=False)`.
   Import as needed. Add/extend coverage in `backend/tests/test_estimator.py` and a
   simulator-driver test. Run the suite.
3. **Change 2 — `_EVAL_RESERVE_RATIO`.** Add `_EVAL_RESERVE_RATIO = 0.0` as a module
   constant in `backend/app/evaluation.py`; reference it in the `BudgetLedger(...)`
   builders inside `run_no_intervention_arm`, `run_fixed_rule_arm`, `run_ai_treatment_arm`
   (replacing the literal `1 / 3`). Update numeric expectations in
   `backend/tests/test_evaluation.py` (and any in `test_lifecycle.py`). Run the suite.
   Verified inert: `no_intervention` (incentive always 0 → funded on the non-reserve
   path), `offline_optimal` (no ledger at all). `fixed_rule` and `ai_treatment` change
   intentionally — their columns will not match the pre-spike run.
4. **Go/no-go checkpoint** (end of Sept 3). Suite green and updates were ≲ ½ day →
   continue. Otherwise → docs-only fallback: write both findings against current code +
   current numbers, do the code fix after Sept 5.
5. **Regenerate dev artifact** — `cd backend && uv run python -m app.evaluation`
   (writes `evaluation_report.json`, dev split). **Convergence check:** dump both cells'
   `alpha`/`beta`/`p̂` at end of the AI arm run; confirm they have left Beta(2,2) and
   roughly match realized rates. Capture the actual AI-vs-`fixed_rule` gap + CI.
6. **Single held-out run** — `uv run python -m app.evaluation --split held_out` at the
   canonical budget. This is the headline number. Commit both artifacts (held-out numbers
   into the findings doc; keep an `evaluation_report_held_out.json` for reproducibility).
7. **Docs:**
   - `docs/adr/0006-decision-engine-estimator.md` — dated amendment: online failure
     update was specified-but-dead, now wired at the simulator-driver resolved-outcome
     point.
   - `docs/adr/0016-evaluation-harness-runs-without-reserve.md` — new ADR (use
     `docs/agents/domain.md` / the ADR format).
   - `README.md` — `## Documented findings` section, mechanism before numbers.
   - `docs/evaluation-findings-2026-09.md` — full analysis of both findings.
   - `CONTEXT.md` — one-line implementation-gap note on the Offline-Optimal Allocation
     entry (code is an unconstrained heuristic, not the constrained version described).
   - Dashboard eval panel annotation (frontend) + two sentences for the demo video
     script.
8. **Commit, push the branch.** Stop. The user merges.

---

## Constraints carried from environment / memory

- Honest measurement only — see Q1. Report whatever the numbers say.
- Concise commit messages.
- Do **not** spawn subagents unless the user asks.
- Never push/merge to `master`, never force-push. Enter a worktree before any edit in the
  shared checkout.
- User's north star: demonstrate serious engineering (potential Razorpay internship).
  A pre-committed honest null/negative result with a crisp mechanism writeup is an
  acceptable — arguably stronger — submission than a suspiciously clean win.
- Memory files under
  `C:\Users\varun\.claude\projects\C--Projects-razorpay-razorpay-agent\memory\` — buildathon
  scope, ADR-0014/0015 notes, ticket status.

## Suggested skills for the next session

- **`/tdd`** — Change 1 and Change 2 are both small, test-first work with clear expected
  behavior (a new β update path; three arm builders under a changed reserve constant).
- **`/domain-modeling`** — for `docs/adr/0016-*`, the ADR-0006 amendment note, and the
  CONTEXT.md Offline-Optimal implementation-gap line.
- **`/run`** — to regenerate `evaluation_report.json` and do the held-out run, and to
  sanity-check the dashboard still renders with the new numbers + annotation.
- **`/grill-with-docs`** — only if step 5's convergence check or the held-out run surfaces
  something qualitatively outside the predicted envelope above; otherwise just report it
  per Q1 and keep going.
