# Handoff — P1 eval Scope A shipped; next is ticket 20 (real-Razorpay halted slice)

**Date:** 2026-09-04
**Project:** Razorpay Revenue Recovery (Track 3, Buildathon 2026, solo build)
**Deadline:** 2026-09-05
**This session:** implemented + reviewed + merged P1 evaluation Scope A, regenerated the eval
numbers, wrote the findings docs, and recorded a new halted-subscription empirical result.
All on local `master` (10 commits ahead of `origin`, **not pushed** — user pushes).
**Next session:** implement **ticket 20** —
`.scratch/recovery-engine/issues/20-real-razorpay-halted-subscription-slice.md`.

---

## What this session did (all committed to local `master`, `acc1329..HEAD`)

Read the commit messages for detail; summary:

- **`e52afab`, `a00fe5f`, `030e4d5`** then merge **`4fe8ec2`** — P1 eval **Scope A**:
  1. `backend/app/simulator_driver.py::run_simulated_case` now records `success=False` on every
     resolved-but-unrecovered cycle (the estimator's `β` update was dead code — root cause of the
     spike's "AI arm ties fixed_rule").
  2. `backend/app/evaluation.py` — `_EVAL_RESERVE_RATIO = 0.0` for the three arm builders
     (single-cell estimator has nothing to ration a reserve on). `app/allocator.py` untouched.
  - New **`docs/adr/0016-evaluation-harness-runs-without-reserve.md`**; dated amendment on
    **ADR-0006**; `CONTEXT.md` Reserved-Budget + Offline-Optimal notes.
  - Code review (two-axis, `/code-review since 9f2ddfe`) run; top finding (dangling ADR-0016
    citation) fixed in `030e4d5`. Two judgement-call smells left, rationale in that commit + the
    superseded handoff below.
- **`2034c71`, `83866e3`** — regenerated `backend/evaluation_report.json` (dev) and
  `backend/evaluation_report_held_out.json` (single canonical held-out run). Both verified
  **byte-for-byte reproducible** via `cd backend && uv run python -m app.evaluation [--split held_out ...]`.
- **`9287954`** — **`docs/evaluation-findings-2026-09.md`** (full write-up of Findings 1/2/3),
  README `## Documented findings` section + refreshed held-out table.
- **`80e6a1e`** — halted-subscription: `docs/research/razorpay-test-mode-subscription-halting.md`
  Addendum 2 (transition reproduced 2026-09-03), README softened, **new ticket 20**.

### The P1 headline (now in `docs/evaluation-findings-2026-09.md` and README)

Held-out, 200 cases: **AI vs `fixed_rule` = −₹16.88/case, 95% CI [−₹36.13, +₹0.00]** — a wash /
marginally behind, as pre-committed (Q1: report as-is). AI vs `no_intervention` decisively
positive. 85.8% of offline-optimal. Estimator convergence confirmed (retry cell β 2 → 251,
p̂ 0.34; calibration 0.335 vs 0.332 in the populated bucket). This is done — no further code.

## The new halted-subscription fact (drove ticket 20)

User reproduced `active → halted` in Razorpay test mode on **2026-09-03**: subscriptions test
card `4718 6091 0820 4366`, "Charge this now → Failure" ×4 — 3 failures stay `active`, the 4th
flips `active → halted` directly. This **supersedes** the 2026-08-22 "did not reproduce" result.
**Not yet verified:** whether Razorpay then delivers a `subscription.halted` **webhook**. That
end-to-end proof is exactly what ticket 20 is for.

---

## Next: ticket 20

**Read `.scratch/recovery-engine/issues/20-real-razorpay-halted-subscription-slice.md` first** —
it has the full acceptance criteria and known risks. Also read:

- `docs/research/razorpay-test-mode-subscription-halting.md` (esp. Addendum 2 + the Q1–Q5
  documented answers — retry ladder, no direct-to-`halted` API, dashboard-only mechanism).
- Memory `project-ticket17-pending-manual-execution` (the 2026-09-03 update + the three
  real-API script gotchas: test-mode 429 rate-limiting, `create_case_from_*` commits before the
  gateway call, don't wrap the whole create call in a retry).
- README "Quickstart" `<details>` block — the real-Razorpay `.env` + `ssh -R` tunnel + dashboard
  webhook-registration steps (same setup ticket 17's failed-payment slice used).

**Shape of the work:**
1. **Human-only, user drives:** `.env` with real test-mode credentials
   (`GATEWAY_BACKEND=razorpay`, `RAZORPAY_KEY_ID/SECRET/WEBHOOK_SECRET`, `RAZORPAY_WEBHOOK_URL`);
   `ssh -R` tunnel up; dashboard webhook registered for `subscription.halted` with matching
   secret; drive a subscription to `halted` via Charge-this-now ×4.
2. **Agent + user together:** confirm the `subscription.halted` webhook is *received* at
   `/webhooks/subscription-halted` — capture the raw payload, confirm HMAC-SHA256 verify passes,
   diff the payload shape against `backend/app/webhooks.py::_extract_*` (which was written to a
   hand-built synthetic payload in ticket 12 — a real-vs-synthetic field mismatch is the most
   likely code fix, unknown size, so start early).
3. Confirm one `RecoveryCase` created (`workflow_type=HALTED_SUBSCRIPTION`,
   `source=EventSource.REAL`), event-id dedupe works on a replay.
4. Run one decision cycle. **Record whatever happens** — `decide()` may pick `NO_ACTION` (cold /
   probabilistic cell), or Razorpay may reject `resume_charge`. A documented finding is an
   acceptable outcome, same disposition as ticket 17's failed-payment gaps. Don't force green.
5. Write up: append a result section to the research doc; update the
   `project-ticket17-pending-manual-execution` memory; if fully proven, soften README's remaining
   "webhook delivery unconfirmed" hedges (Quickstart note + "What broke" paragraph).

**Caps / hazards:** 30 Payment-Links per test-mode business; card tokens valid 3 days; test mode
429s on rapid requests. Per repo convention **do not** tick ticket 17's checkbox in its file.

---

## Also still open (step 7 items 5–6 from the superseded handoff)

Not blocking, not started:
- **Dashboard eval-panel** one-line pointer to `docs/evaluation-findings-2026-09.md` (frontend —
  check the panel component exists first).
- **Demo video script** — 2 sentences owning Findings 1 & 2. (Independent of ticket 20.)
- The *halted-subscription* lines of the demo narrative should wait for ticket 20's outcome
  (proven vs still-synthetic changes the wording).

## Superseded / prior artifacts (reference, don't redo)

- `docs/agent-handoffs/2026-09-04-01-handoff-p1-eval-scope-a-done.md` (committed) — its steps 1–4
  and doc-items 1–4 are **done**; its "predicted result" section is confirmed. Only its
  step-7 items 5–6 remain (above).
- `docs/agent-handoffs/2026-09-03-03-handoff-p1-eval-fix-plan.md` — the Scope A plan, now executed.
  (Present as an **untracked** file in the working tree — the user's, leave it.)
- `SPIKE_FINDINGS.md` / branch `prototype/p1-eval-spike` — the failed spike, throwaway.

## Working-tree state (leave alone)

`git status` shows a pre-existing unstaged `test2108.md` deletion and the untracked
`docs/agent-handoffs/2026-09-03-03-*.md` (identical 233-line counts — a move the user started).
Not this session's; not staged into any commit. Don't touch.

## Constraints (from memory + environment)

- **Never push or merge to `origin`/`master`** — user does their own merges. Local `master` is
  10 commits ahead of `origin`; user pushes when ready.
- Concise commit messages. End with `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`.
- Enter a worktree before code edits in the shared checkout.
- Do **not** spawn subagents unless the user asks (the `/code-review` sub-agents this session
  were the skill's own design).
- `uv run` **must** be invoked from `backend/`, not the repo root (else `ModuleNotFoundError`).
- User's north star: serious engineering, potential Razorpay internship. Honest documented
  findings > forced wins.

## Suggested skills for the next session

- **`/wizard`** — for ticket 20's human-only setup (real `.env` credentials, `ssh -R` tunnel,
  Razorpay dashboard webhook registration, driving the subscription to `halted`). Generates a
  bash walkthrough so it's not re-explained each session.
- **`/run`** — bring the backend up against `GATEWAY_BACKEND=razorpay` and watch
  `/webhooks/subscription-halted` logs end-to-end.
- **`/diagnosing-bugs`** — if the `subscription.halted` webhook doesn't arrive, signature verify
  fails, or the payload shape mismatches `webhooks.py::_extract_*`. It wants a tight repro loop
  first (one command that reproduces the failure).
- **`/implement`** or **`/tdd`** — for any code fix that falls out (most likely a real-vs-synthetic
  payload-shape adjustment in `_extract_*`, with a regression test).
- **`/domain-modeling`** — only if a real payload reveals a modelling gap worth an ADR
  (e.g. Subscription still has no amount field → `case_value` 0 → `RESUME_CHARGE` outside the
  budget game, per ADR-0014; a real halted case might make that worth revisiting).
