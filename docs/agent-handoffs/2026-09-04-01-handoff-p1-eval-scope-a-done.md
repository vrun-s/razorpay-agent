# Handoff — P1 evaluation fix Scope A: code done + reviewed, numbers not yet regenerated

**Date:** 2026-09-04
**Project:** Razorpay Revenue Recovery (Track 3, Buildathon 2026, solo build)
**Deadline:** 2026-09-05
**This session:** executed Scope A (Changes 1 & 2) from
`docs/agent-handoffs/2026-09-03-03-handoff-p1-eval-fix-plan.md` via `/implement`, then
`/code-review` (two-axis, parallel sub-agents), then addressed the review. Three commits
on an un-merged branch. **No evaluation numbers regenerated yet.**
**Next session:** run steps 5–8 below — regenerate the dev artifact + convergence check,
the single held-out run, the remaining docs, then the user merges.

---

## Where the work is

- **Worktree:** `.claude/worktrees/p1-eval-failure-update/`, branch
  `worktree-p1-eval-failure-update`.
- **Branched off `origin/master` @ `9f2ddfe`.** Local `master` is one docs-only commit
  ahead (`acc1329` — "docs: P1 eval spike findings + result handoff"); irrelevant to this
  code. The user does their own merges — **do not merge or push.**
- **Three commits** (`git log 9f2ddfe..HEAD`):
  - `e52afab` — Change 1: estimator failure update in the simulator driver.
  - `a00fe5f` — Change 2: `_EVAL_RESERVE_RATIO = 0.0` in the eval arm builders.
  - `030e4d5` — review fixes: new `docs/adr/0016-*`, `CONTEXT.md` pointer, docstring/
    comment corrections, test import tidy.
- **Tests:** baseline `uv run pytest` was **256 passed**; now **258 passed** (+2 new).
  No regressions. Full suite green at every commit.

## What changed (the two Scope-A changes)

### Change 1 — `backend/app/simulator_driver.py::run_simulated_case`
New branch in the reassessment loop, right after the `mark_recovered` branch and before
the `case.status != OPEN or cycle >= _MAX` break:

```python
if outcome.resolved and not outcome.recovered:
    cell_key = resolve_last_decided_cell_key(case)
    if cell_key is not None:
        get_estimator().update(cell_key, source=case.source, success=False)
```

New imports: `resolve_last_decided_cell_key` from `app.decision`, `get_estimator` from
`app.estimator` (no import cycle — `app.lifecycle`, already imported here, imports the
same two). Covers a failed executed intervention **and** a NO_ACTION cycle with no
spontaneous recovery. Recorded **once per failed cycle** (not terminal-only) — matches
Q6 in the 2026-09-03-03 handoff ("most Bernoulli trials → fastest convergence"). Before
this, the estimator only ever saw `success=True`; β stayed pinned at the Beta(2,2)
cold start and every retry cell inflated toward 1.0 (the spike's root cause).

Test: `test_an_unrecovered_cycle_feeds_a_failure_back_into_the_estimator` in
`backend/tests/test_simulator_driver.py` — drives a 20-case population, asserts the
`(insufficient_funds, new, payment_retry)` cell's `beta > _COLD_START_BETA`. It reaches
`get_estimator()._cell(...)` deliberately (must prove β moved, not the mean).
`test_estimator.py` was **not** touched — its `success=False` unit path
(`test_simulated_failure_decreases_the_point_estimate`) already existed; the real gap
was the caller, which the driver test now covers.

### Change 2 — `backend/app/evaluation.py`
`_EVAL_RESERVE_RATIO = 0.0` module constant (in the "Shared arm constants" block),
substituted for the literal `1 / 3` in the `BudgetLedger(...)` builds inside
`run_no_intervention_arm`, `run_fixed_rule_arm`, `run_ai_treatment_arm`.
`run_offline_optimal_arm` has no ledger. `app/allocator.py::_DEFAULT_RESERVE_RATIO = 1/3`
is **untouched** — live/demo paths still reserve a third; `demo_seed.py` still exercises
the reserve mechanism.

Rationale (now in `docs/adr/0016-evaluation-harness-runs-without-reserve.md`): the eval
estimator collapses to one non-trivial cell (`failure_reason` always `insufficient_funds`
via the fixed decline text + FakeLLM; `customer_segment_proxy` always `NEW` via
`order_count=1`). A truthful retry `p̂` converges below the allocator's `0.5` min-quality
gate, so the reserved third would be stranded for the AI arm while `fixed_rule` (fed a
hardcoded `0.5`) spends through — an artefact of the single-cell harness, not a real
allocation decision. This is **Finding 1** from the 2026-09-03-03 handoff.

Test: `test_eval_arms_run_without_a_budget_reserve` in `backend/tests/test_evaluation.py`.

## Code review outcome (both axes)

Full two-axis report is in this session's transcript. Summary:

- **Both axes' top finding:** `_EVAL_RESERVE_RATIO` cited `ADR-0016`, which did not
  exist. **Fixed in `030e4d5`** — ADR-0016 written (format matches ADR-0015), inline
  comment trimmed to a pointer, `CONTEXT.md` Reserved Budget entry gets a one-line
  cross-reference, `run_fixed_rule_arm`'s docstring corrected (it still claimed the
  reserve-quality gate runs).
- **Spec (a):** `test_estimator.py` not extended — assessed and left (see Change 1 above).
- **Standards #3 (module-split smell):** the failure update lives in the driver, not
  `lifecycle.py` beside the success update. **Left deliberately** — non-recovery is
  genuinely observed in the driver's `_resolve_cycle_outcome`; there is no `mark_failed`
  lifecycle transition to host it in. `mark_recovered` is in lifecycle because it *is* a
  real state transition; a looping failed cycle is not.
- **Standards #4 (3-site `BudgetLedger` duplication):** pre-existing shape, the sites
  differ in budget source (`policy.recovery_budget` vs `DEFAULT_MERCHANT_CONFIG...`); a
  `_fresh_arm_allocator()` helper is a refactor out of this change's scope.

## Course of action — remaining steps (from 2026-09-03-03 handoff, steps 5–8)

Run from the worktree, `cd backend` first. `uv run` **must** be invoked from
`backend/` — from the repo root it fails with `ModuleNotFoundError: No module named
'sqlmodel'`.

5. **Regenerate the dev artifact** — `uv run python -m app.evaluation` (writes
   `evaluation_report.json`, dev split). **Convergence check:** dump both cells'
   `alpha`/`beta`/`p̂` at the end of the AI arm run; confirm they have left Beta(2,2) and
   roughly match realized rates. Capture the AI-vs-`fixed_rule` gap + bootstrap CI.
6. **Single held-out run** — `uv run python -m app.evaluation --split held_out` at the
   canonical `DEFAULT_MERCHANT_CONFIG` budget. Run **once**, after code + dev numbers are
   frozen. Whatever it says is the README headline (Q1: honest measurement only — report
   as-is). Keep an `evaluation_report_held_out.json` for reproducibility.
7. **Docs:**
   - `docs/adr/0006-decision-engine-estimator.md` — dated amendment note: the online
     failure update was specified ("β += 1 on failure") but had no live caller until now;
     wired at the simulator-driver resolved-outcome point. (Bug-fix note, not a new
     decision.)
   - `README.md` — `## Documented findings` section, **mechanism before numbers**, both
     Findings, linking to the full analysis.
   - `docs/evaluation-findings-2026-09.md` — full write-up of Finding 1 (reserve /
     single-cell, → ADR-0016) and Finding 2 (greedy `decide()` + cold-start Beta(2,2)
     oscillation — accepted, not fixed).
   - `CONTEXT.md` — one-line implementation-gap note on the **Offline-Optimal Allocation**
     entry (the code is an unconstrained heuristic — costs 0, guaranteed attempts — not
     the constrained version the entry now describes). Separate from the Reserved-Budget
     pointer already added this session.
   - Dashboard eval panel: one-line pointer to the findings doc (frontend).
   - Demo video script: two sentences owning both Findings.
8. **User merges** the branch. Then delete the worktree.

## Design decisions still governing (from 2026-09-03-03, do not re-litigate)

- **Q1 — honest measurement only.** No parameter chosen by "does AI win". Pre-committed:
  if held-out shows AI ≤ `fixed_rule`, that is the headline; demo narrative shifts to
  "when does learned allocation beat a flat rule, and when doesn't it."
- **Predicted result:** AI tracks `fixed_rule` closely except during the Finding-2
  oscillation window, where it under-recovers. Headline likely **AI trails `fixed_rule`
  by a modest margin, bootstrap CI straddling 0 or slightly negative.** Sign is
  knife-edge. If step 5/6 lands *qualitatively* outside this envelope, report it per Q1
  and keep going — only `/grill-with-docs` if it is genuinely bizarre.
- **Q5** — `_EVAL_RESERVE_RATIO = 0.0` (done). **Q6** — failure per resolved-but-failed
  cycle (done). **Q9** — Finding-2 oscillation accepted, documented, not fixed.
- **Deferred past 2026-09-05:** relative/opportunity-cost reserve gate; the `decide()`
  exploration gap; per-case `case_value` + real `failure_reason` dispersion (needs a
  frozen-simulator change + `SIMULATOR_VERSION` bump + held-out regeneration); possibly
  reopening ADR-0014 for learnable discount-sensitivity.

## Constraints carried from environment / memory

- Concise commit messages.
- Do **not** spawn subagents unless the user asks (the `/code-review` sub-agents this
  session were the skill's own design).
- Never merge/push to `master`, never force-push. Stay in the worktree for edits.
- User's north star: demonstrate serious engineering (potential Razorpay internship). A
  pre-committed honest null/negative result with a crisp mechanism write-up is an
  acceptable — arguably stronger — submission than a suspiciously clean win.
- Memory files under
  `C:\Users\varun\.claude\projects\C--Projects-razorpay-razorpay-agent\memory\`.

## Suggested skills for the next session

- **`/run`** — steps 5–6 (regenerate `evaluation_report.json`, the held-out run), and to
  sanity-check the dashboard still renders with the new numbers + annotation.
- **`/domain-modeling`** — the ADR-0006 amendment note and the CONTEXT.md Offline-Optimal
  implementation-gap line.
- **`/grill-with-docs`** — only if step 5's convergence check or the held-out run is
  qualitatively outside the predicted envelope.
