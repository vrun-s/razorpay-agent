# Handoff — P1 evaluation rebuild: spike first, then clean build

**Date:** 2026-09-03
**Project:** Razorpay Revenue Recovery (Track 3, Buildathon 2026, solo build)
**This session:** a `/grill-with-docs` session that sequenced the "fix everything" improvement plan into an ordered set of phases. No code changed; two decision docs committed.
**Next session:** run the **Phase 1 spike** (below) as a `/prototype` on a scratch branch, then check the kill criteria.

---

## What is already written down (do not re-derive)

- **Commit `6e52f84`** on branch `worktree-spike-independent-docs` (pushed to origin, not merged to master):
  - `CONTEXT.md` — *Offline-Optimal Allocation* entry tightened with the four non-cheating constraints.
  - `docs/adr/0013-evaluation-metric-baselines-contract.md` — dated amendment: estimator-blind arms (`fixed_rule`, `no_intervention`) skip the value-aware allocator gates by carrying `point_estimate is None`.
- Standing project context: `README.md`, `CONTEXT.md`, `docs/adr/` (esp. **0003** streaming allocation, **0006** Beta-Bernoulli estimator / never an LLM guess, **0007** evaluation integrity, **0013** eval contract, **0014** flat incentive / learnable deferred, **0015** hosted demo), `.scratch/recovery-engine/spec.md`.
- Prior handoff: `docs/agent-handoffs/2026-09-01-01-handoff-portability-discussion.md` (LLM seam facts, portability plan).
- Memory files under `C:\Users\varun\.claude\projects\C--Projects-razorpay-razorpay-agent\memory\` — buildathon scope, ticket status, ADR-0014/0015 notes.

## The prior assessment this plan responds to

Earlier in the same conversation thread (before the grilling): a brutal-honesty review concluded the project's headline evaluation result is **weak** — the AI treatment arm ties / slightly trails the flat-5% `fixed_rule` baseline on NRR. Root cause, verified in code: every eval case carries an identical ₹500 value, a flat 5% incentive, and a barely-binding ₹10,000 budget, so the streaming allocator has no economic selection problem to solve and `decide()` maximises probability, not expected value. The plan below targets that root cause.

---

## The settled plan (this is the payload — it is nowhere else)

### Phase 0 — De-risk, runs in parallel, no code dependency

**P2a — manual Razorpay test-mode transaction (user runs this).** User confirmed a test-mode account exists. Goal: push one full failed-payment → recovery loop by hand and log what breaks.

1. Credentials into repo-root `.env`: `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` (user-chosen string, mirrored into dashboard), `RAZORPAY_WEBHOOK_URL=https://<tunnel>/webhooks`, `GATEWAY_BACKEND=razorpay`.
2. Start the webhook tunnel (README "Running against real Razorpay test mode" section).
3. Dashboard → Webhooks: register `<tunnel>/webhooks/payment-failed`, `/webhooks/payment-captured`, `/webhooks/subscription-halted`; subscribe events `payment.failed`, `payment.captured`, `subscription.halted`; secret matches `.env`.
4. Drive: failing payment → `payment.failed` creates a case → decision cycle proposes retry / Payment Link → pay that with a success card → `payment.captured` matches case by `external_reference_id` → case RECOVERED.
5. Watch backend logs end-to-end. Capture: SDK 4xx/5xx, signature-verification failures, payload-shape mismatches vs `webhooks.py::_extract_*`, and **whether `subscription.halted` is triggerable at all in test mode** (memory hints it may not be — a null result there is itself a finding).
6. Report back: completed end-to-end? what broke, with request/response.

Not a ticket, does not block the spike.

### Phase 1 — The spike (throwaway, scratch branch, ~1-day time-box) — **NEXT SESSION**

One question: **does the AI arm separate from `fixed_rule` on NRR in the constrained-budget regime?** — answered before any clean investment. Hacked, no tests, no cleanup.

Five changes:

1. **`backend/app/simulator/generator.py`** — `_generate_one_case` draws, onto `SimulatedCase` / `HiddenGroundTruth`:
   - per-case `case_value` — lognormal, median ≈ ₹500 (`50_000` paise), p95 ≈ ₹6k, hard cap.
   - per-case `failure_reason` (realistic mix over `llm.py::FAILURE_REASON_CATEGORIES`) **+ matching decline text**. **This is a hard dependency, not optional** — without `failure_reason` dispersion the estimator's `(failure_reason × segment_proxy × intervention)` cells don't separate and a null spike result is uninformative (see "Key facts" — the eval currently pins every case to `insufficient_funds`).
2. **Thread `simulated.case_value` through all four arms** in `backend/app/evaluation.py` (replace the scalar `case_value=DEFAULT_CASE_AMOUNT` param reads); `simulator_driver.py::_failed_payment_payload` emits per-case `amount` + decline text.
3. **`backend/app/decision.py`** — add `case_value` to `DecisionInput`; change `decide()` objective to expected value. **Expect this to be near-cosmetic**: under ADR-0014's flat incentive, `case_value` cancels and it reduces to `p̂_retry − p̂_noaction > incentive_pct`. (This is a deliberately-accepted finding, see Q13 below — not a problem to fix.)
4. **`backend/app/allocator.py`** — add `expected_net_value` to `AllocationCandidate` **alongside** `point_estimate`/`uncertainty` (not a replacement); make `point_estimate: float | None`. Two gates, **both apply iff `point_estimate is not None`**:
   - EV margin gate (bites on available-pool funding decisions): `p̂ − uncertainty/2 > incentive_pct`
   - reserve quality gate (unchanged): `p̂ − uncertainty/2 ≥ min_quality_score` (`0.5`)
   - `fixed_rule` / `no_intervention` pass `point_estimate=None` → neither gate runs, today's treatment preserved, allocator stays structurally identical across arms.
5. **`backend/app/evaluation.py::run_offline_optimal_arm`** — make it non-cheating: same Recovery Budget (no reserve), pays the same incentive cost per executed intervention, **same bounded retry ceiling** as the online arms (not today's unbounded attempts), same per-workflow valid-intervention set. Implement as greedy 0/1 selection by NRR-per-incentive-rupee, label it a heuristic upper bound.

**Run:** `run_evaluation` on the **dev split only** (300 cases), at budgets **₹2k / ₹5k / ₹10k / ₹25k / ₹50k**.

**Kill criteria — proceed to Phase 2 only if:** at the two tightest budgets — AI-vs-`fixed_rule` bootstrap NRR gap point estimate positive, CI lower bound ≥ 0 at ≥ 1 level, **and** AI captures a higher % of the (now budget-constrained) offline-optimal than `fixed_rule` does. Otherwise **stop and go back to `/grill-with-docs`** to rethink P1 — no tickets, no clean build.

Time-box the spike to ~1 day; if the arms fight the change harder than that, that is itself signal that clean P1 is a 3-day job not 1.5 — replan rather than push through.

### Phase 2 — Clean P1 (only if the spike clears)

Feature branch, **stepwise commits, full test suite green at every step, merge each green step straight to master** (solo project — skip PR ceremony). Keep the spike branch alive until step 6 reproduces its numbers.

**Docs to write first (see "Artifacts still owed" below):** ADR (case_value + failure_reason simulator model) and ADR (evaluation tuning discipline) before step 1; the ADR-0013 amendment + CONTEXT Offline-Optimal edit are already done (`6e52f84`).

Steps, in dependency order:

1. Generator — `case_value` + `failure_reason` + decline text, with generator tests.
2. Thread-through — `evaluation.py` arms, `DecisionInput`, live lifecycle path picks up `amount`.
3. `decide()` — the EV threshold shift.
4. Allocator — `expected_net_value`, `point_estimate: float | None`, both gates gated on estimate presence, **EV margin gate frozen at `p̂ − uncertainty/2 > incentive_pct`** (the uncertainty-discounted form, so sparse-cell optimism can't buy funding — see Q18).
5. Offline-optimal — the non-cheating knapsack.
6. Budget-sweep harness + the AI / fixed_rule / offline-optimal vs-budget plot; wire into the `evaluation_report.json` artifact / dashboard.
7. Regenerate dev + validation numbers. **Freeze `reserve_ratio = 1/3` and `min_quality_score = 0.5`.** Touch a hyperparameter only if the dev sweep is pathological, and only as a validation-confirmed, ADR-recorded change. **No hyperparameter search.**
8. **Single held-out run — the full sweep curve, one script invocation, no per-point inspect-then-adjust.** Whatever it reports is the headline.

Then: README "documented findings" entry — `decide()` EV-maximisation is near-cosmetic under ADR-0014's flat incentive; the real lever is allocator EV-gating.

### Phase 3 — Post-fundamentals (after Phase 2 numbers frozen; video deprioritised, user says there is time)

Order: **P3** (frontend efficiency counter + reserve-budget demo beat; needs frozen P1 numbers) → **P4** (LLM system prompt + few-shot for `diagnose_failure_reason` + calibration curve on screen; **zero eval impact**, live/real path only) → **P2b** (stable named webhook URL, repackaged README, recorded real transaction) → **P5/P6** (assemble video, last).

---

## Key design decisions from the grilling (rationale, since it is nowhere else)

- **Q13 — `decide()` EV change is accepted as near-cosmetic**, not worked around. Under flat incentive `V` cancels from the retry-vs-no-action comparison. Not reopening ADR-0014 (no per-case learnable discount). Story stays: *"the AI allocates a fixed budget better using learned per-cell recovery odds."* Document as a key finding (evaluators want documented issues/deferrals).
- **Q14 — allocator stays identical across all arms** (ADR-0013 non-confound). The AI's entire structural edge = real per-cell `p̂` vs a flat `0.5` prior. This makes the `failure_reason` generator work (Q7) a **hard dependency of the spike**, not a nice-to-have.
- **Q7 — fix the generator** (option 2): draw per-case `failure_reason` + decline text so the estimator's 3rd axis is actually exercised end-to-end. Fallback if the spike fails: disclose-only in README.
- **Q9 — offline-optimal non-cheating**: four constraints (same budget/no-reserve, pays incentive, same bounded retries, same valid-intervention set). Foresight limited to per-case recoverability + value. Greedy heuristic, labelled as such.
- **Q17 — estimator-blind gate skip** is a *consequence* of `fixed_rule`'s "no Decision Engine estimate" definition, implemented as `point_estimate is not None and …`, never `arm == "fixed_rule"`. Both allocator gates skipped when `point_estimate is None`; candidate keeps today's treatment. (Committed in `6e52f84`.)
- **Q18 — EV gate uses a margin, not exactly-0**: `p̂ − uncertainty/2 > incentive_pct`, the same uncertainty-discounted `p̂` the reserve gate uses. Frozen for the headline run. If the dev sweep shows it is too conservative (declining cases that would clearly have cleared), that is the tunable-if-pathological direction to file.
- **Q10 — tuning discipline**: frozen-forever (prior, update rule, bootstrap, arm defs, seeds, split sizes, `FIXED_RULE_DISCOUNT_PCT = 5.0`); set-once-by-judgment-then-frozen (`case_value` distribution, `failure_reason` mix — pick to look like plausible SME data, document, do **not** pick what makes AI win); tunable-on-dev-confirmed-on-validation (`reserve_ratio`, `min_quality_score`, budget grid); held-out touched once.
- **Q15 — held-out = full sweep curve, one run.** More honest than cherry-picking a budget level, still one touch.

## Artifacts still owed (write as preconditions land — see /ask-matt flow answer)

1. **New ADR** — simulator gains per-case `case_value` + `failure_reason`: the distribution/mix shapes, why those, why frozen-by-judgment. (Before clean-P1 step 1.)
2. **New ADR** — evaluation tuning discipline: the Q10 frozen/set-once/tunable/held-out table. (Before clean-P1 step 1.)
3. **ADR-0013 amendment** — ✅ done (`6e52f84`).
4. **CONTEXT.md** — Offline-Optimal Allocation ✅ done (`6e52f84`); still to add: **Case Value** term, **Budget Sweep** / **Constrained-Budget Regime** term.
5. **README "documented findings"** — the `decide()`-is-cosmetic-under-flat-incentive point. (After the spike confirms the mechanism.)

## Key facts discovered this session (so the next agent does not re-derive)

- **The eval harness runs entirely on `FakeLLMClient`** (no `ANTHROPIC_API_KEY` in eval context). `simulator_driver.py::_failed_payment_payload` hardcodes `"error_description": "insufficient funds in account"` for *every* simulated case → `FakeLLMClient.diagnose_failure_reason` returns `insufficient_funds` for all 650 cases. So in evaluation the estimator's `failure_reason` axis is a **constant** — the effective cell key is `segment_proxy × intervention`. This is why P4 (LLM prompt fix) changes **zero** eval numbers and why Q7's generator fix is load-bearing.
- `case_value` is **already** a scalar parameter threaded through `run_evaluation` → all four arms → `policy.validate(..., case_value=...)`. `DEFAULT_CASE_AMOUNT = 50_000` in `simulator_driver.py`. P1.1 is a data-model change (per-case field + distribution + swap the reads), not new plumbing.
- `decision.py::decide()` = `max(candidates, key=lambda i: estimator.estimate(...).point_estimate)` over a 2-tuple per workflow (`PAYMENT_RETRY`/`NO_ACTION` or `RESUME_CHARGE`/`NO_ACTION`). `DecisionInput` has no `case_value` axis, no EV calc.
- `allocator.py::StreamingAllocator.decide()` — funds freely if `incentive_amount ≤ available` (non-reserved pool); else only if `point_estimate − uncertainty/2 ≥ min_quality_score` (`0.5`) to draw against the reserve (`reserve_ratio = 1/3` of `remaining`). No `expected_net_value` anywhere. `fixed_rule` / `no_intervention` currently feed `point_estimate=0.5`, `uncertainty=0.0`.
- `evaluation.py::run_offline_optimal_arm` currently costs **0**, ignores budget, gives each candidate **unbounded** attempts (docstring explicitly defers the budget-constrained knapsack). `_case_seed(run_seed, case_index) = (run_seed * 1_000_003 + case_index) % 2**31`. Splits: `DEV_SIZE=300`, `VALIDATION_SIZE=150`, `HELD_OUT_SIZE=200`, `DEFAULT_DATASET_SEED = 20260826`. `bootstrap_gap_ci` `n_resamples=10_000`. `run_evaluation` defaults `workflow_type=FAILED_PAYMENT` because `HALTED_SUBSCRIPTION`'s `case_value` always resolves to 0 (Subscription has no amount field).
- `merchant_config.py` — `MerchantConfig(recovery_budget=1_000_000, incentive_pct=5.0)`; `DEFAULT_MERCHANT_CONFIG.recovery_budget = 1_000_000` paise (₹10,000).
- `config.py` — `razorpay_key_id/secret/webhook_secret/webhook_url`, `gateway_backend: "fake"|"razorpay"`, `anthropic_api_key`, all from repo-root `.env`.
- `webhooks.py` — 3 routes: `/webhooks/payment-failed` (`payment.failed`), `/webhooks/subscription-halted` (`subscription.halted`), `/webhooks/payment-captured` (`payment.captured`, matches case by `external_reference_id`). Real HMAC-SHA256 verification, `x-razorpay-event-id` dedupe.
- `llm.py::FakeLLMClient` — keyword-matches decline text against an 8-entry table; `generate_justification` is a fixed template; `flag_escalation` keyword-matches. Model hardcoded `claude-haiku-4-5-20251001`, no system prompt.
- Backend test suite: ~251 tests, run green as of session start. The P1 changes will break tests in `test_decision`, `test_allocator`, `test_evaluation`, `test_policy`, and the simulator tests.
- `case_value` also appears in `lifecycle.py`, `policy.py`, `observability.py`, `main.py`, `routers/webhooks.py`, `models.py` — the thread-through surface is wider than generator + evaluation.

## Suggested skills for the next session

- **`/prototype`** — the Phase 1 spike is exactly this: throwaway code answering one design question, kept on a `prototype/<name>` branch as a primary source, referenced from the eventual implementation issue.
- **`/grill-with-docs`** — only if the spike **fails** the kill criteria: go back and rethink P1 rather than proceed.
- **`/to-spec`** then **`/to-tickets`** — only if the spike **passes**: collapse Phase 2's 8 steps + the two owed ADRs into a spec, then tracer-bullet tickets under `.scratch/recovery-engine/issues/` worked blockers-first, `/implement` per ticket with `/clear` between.
- **`/domain-modeling`** — when writing the two owed ADRs and the Case Value / Budget Sweep CONTEXT terms.

## Constraints carried from the environment / memory

- User wants **concise commit messages**.
- Do **not** spawn subagents unless the user asks.
- Never push to master/main, never force-push, never merge — user does their own merges (solo repo, PRs #1/#2 were multi-session handoffs).
- Enter a worktree before any code edits in the shared checkout.
- User's north star: demonstrate serious engineering, potentially land a Razorpay internship — not just technically fit the track. Size suggestions to solo/full-time capacity.
