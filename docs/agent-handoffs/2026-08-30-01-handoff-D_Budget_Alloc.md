# Handoff — CRUCIAL DISCUSSION session: budget-allocation design decision → ticket 19

**Repo:** `C:\Projects\razorpay\razorpay-agent` (branch `master`)
**Date written:** 2026-08-30
**Next session focus (per user):** implement **ticket 19** — `.scratch/recovery-engine/issues/19-live-incentive-cost-budget-allocation.md`.

This session was almost entirely a **design discussion** (a `grill-with-docs` run: `grilling` + `domain-modeling` skills, 4 question rounds). Almost no code was written — the output is a decision, an ADR, a CONTEXT.md term, and a fully-specced ticket. The next session does the building.

---

## Read these first (do not re-derive — this handoff deliberately does not repeat them)

| Artifact | What it holds |
|---|---|
| `docs/adr/0014-flat-incentive-response-learnable-deferred.md` | **The decision.** Flat incentive-response model now; learnable "discount-sensitivity" version deferred. Full rationale, the eval-integrity boundary, tunable defaults. |
| `.scratch/recovery-engine/issues/19-live-incentive-cost-budget-allocation.md` | **The work.** Verified construction sites, scope checkboxes, the decline-vs-never-in-loop guard, held-out regeneration discipline, out-of-scope list, narrative guard. |
| `CONTEXT.md` | New **Incentive** term; **Recovery Budget** sharpened to "Incentive spend". |
| auto-memory `project_budget_allocation_flat_incentive.md` | One-paragraph decision record so this isn't re-litigated. |
| `docs/agent-handoffs/2026-08-27-01-handoff.md` | Prior handoff — first framed the budget-allocation problem and the halted-subscription `case_value=0` gap. |

---

## Uncommitted working-tree state (nothing committed this session)

```
 M CONTEXT.md                                                        (Incentive term)
?? docs/adr/0014-flat-incentive-response-learnable-deferred.md       (new)
?? .scratch/recovery-engine/issues/19-live-incentive-cost-budget-allocation.md  (new)
```
HEAD is still `77a4949`. Also written, outside the repo: `~/.claude/projects/C--Projects-razorpay-razorpay-agent/memory/project_budget_allocation_flat_incentive.md` + a line in `MEMORY.md`.

The next agent can commit these three docs as a unit (e.g. `docs: ADR-0014 + ticket 19 for live incentive cost`) before starting implementation, or fold them into the first implementation commit. User prefers **concise commit messages** (memory `feedback_concise_commit_messages`).

---

## How the decision was reached (the part not in the ADR)

The design tree, round by round — the ADR records the destination, this records why the branches fell:

- **What consumes the Recovery Budget?** → an **Incentive** (merchant-funded discount) bundled with `PAYMENT_RETRY`/`RESUME_CHARGE`. Rejected: operational cost (too small to make the reserve mechanism matter); a standalone `WINBACK_OFFER` intervention (doubles the engine's action space for little gain).
- **Discovery mid-discussion that reshaped everything:** `app/simulator/response_curves.py` models `p(recover)` on `(persona × intervention)` only — **no incentive dimension anywhere**, and it's frozen under ADR-0007. So "bundle a discount" alone would still leave the budget inert (allocator correctly learns spending buys nothing).
- **Does an incentive move recovery odds, and is it learnable?** Two real options:
  - **(a) learnable** — per-persona uplift curves + `incentive` axis on `EstimatorCellKey` + engine sub-decision. Supports the "agent learned who's discount-sensitive" narrative.
  - **(b) flat** — one uniform `+uplift` when funded, no estimator change. Narrative is "budget pacing under a reserve", no learning claim.
- User initially leaned (a) for the narrative, then asked for a **risk assessment given project state**. Risks that decided it against (a) *for now*: ~5× blast radius across done tickets 02/05/06/07/08/10/15/18; forces regenerating the committed held-out `evaluation_report.json` with real chance the numbers come out *less* clean; doubling estimator cells against a fixed 300-case dev split risks thin/contrived-looking convergence; friction with ADR-0006's deliberately-greedy engine.
- **Resolution:** ship (b) now — it is a strict subset of (a)'s plumbing, not throwaway — and layer (a) later **only if demo time allows**. Before ever committing to the (a) narrative: check per-cell observation counts on the 300-case dev split.

Locked parameters: `INCENTIVE_UPLIFT = 0.10`, `incentive_pct = 5.0`, degrade-to-free-retry on allocator decline, `MerchantConfig` unifies the two `recovery_budget` copies, `FAILED_PAYMENT` scope only.

---

## The user's own methodological calls (preserve these — they signal what the user cares about)

The user personally flagged each of these; the next agent should treat them as requirements, not suggestions:

1. **`incentive_pct` as a separate constant** numerically equal to `FIXED_RULE_DISCOUNT_PCT` but not shared — "the more important methodological call of the three." Keeps AI vs fixed-rule differing only in *when they fund* and *which intervention*, never discount size.
2. **Demo-vs-eval boundary.** The demo `recovery_budget` sizing and case-ordering (low-quality case before high-quality so the reserve visibly bends) are **walkthrough-seed only**. The eval harness keeps its canonical `MerchantConfig` budget + `DEFAULT_DATASET_SEED`. A demo knob reaching an eval run = regression against ADR-0007. Must be written into the ticket (it is) and honoured in code.
3. **Grep, don't assume, the construction site.** Done this session — `lifecycle.py:148` confirmed the only live-flow site; ticket 17 added none. Ticket 19 lists the two eval sites + the stale "always 0" comments/assertions to sweep (`observability.py:53`, `evaluation.py:340/403`, `test_observability.py:45`).
4. **Decline ≠ never-in-loop.** A `RESUME_CHARGE` with structurally-zero `incentive_amount` must not be logged/displayed as "allocator declined" — the allocator was never consulted. Different fact. Dashboard/audit/Case History must distinguish.
5. **`ai_treatment` non-zero spend = fastest did-it-work check.** After regenerating the report, confirm AI-arm total incentive spend is no longer identically 0 *before* analysing NRR deltas — that zero was the original symptom.
6. **Held-out = mechanism update, not tuning.** The 200 held-out case identities + order stay byte-identical; only the response-curve function changes. Say so explicitly in the commit/PR text (it's one sentence from looking like the thing ADR-0007 prohibits). Disappointing regenerated numbers stand — no constant-fiddling to rescue them.

---

## Sub-decisions still open (resolve during implementation, record any deviation against ADR-0014)

- **Exact demo `recovery_budget`** — ADR gives a sizing heuristic (~40–60% of expected total incentive demand for the demo seed); the number itself is set when `demo_seed.py` is regenerated.
- **Case History shape for three states** — funded incentive / declined incentive (allocator said no, free retry ran) / no incentive on the table. Needs a representation the dashboard and audit trail can render distinctly (see methodological call #4).
- **`case_value` source in `lifecycle.py`** — today `payment.get("amount", 0)` is passed as `case_value` to `validate()`. Confirm that's the right basis for `incentive_amount = round(case_value * incentive_pct)`.
- **`BudgetTimeline.tsx`** — drop the amber disclaimer; consider a visual marker where the allocator declined a case (prior handoff also suggested this).

---

## Deferred — possible ticket 20

The learnable incentive-response version ("agent learns which customer-segment proxies are actually moved by an incentive"). Would supersede part of ADR-0014. Gate on: demo is otherwise solid + time remains + per-cell dev-split observation counts look healthy.

---

## How to run / verify (unchanged from prior handoff)

| Task | Command (from `backend/` unless noted) |
|---|---|
| Backend tests | `uv run pytest` (224 passing at session start) |
| Backend API | `uv run uvicorn app.main:app --port 8000` |
| Frontend | `npm run dev` (from `frontend/`) → http://localhost:5173 |
| Seed demo DB | `uv run python -m app.demo_seed` |
| Regenerate eval artifact | `uv run python -m app.evaluation` (dev split; `--split held_out` only for the final headline run) |
| Frontend check | `npm run build && npm run lint` (from `frontend/`) |

---

## Suggested skills for the next session

- **`tdd`** — ticket 19 reopens seams in tickets 05/06/10/15; build the new cost path test-first at those seams. Established per-ticket flow.
- **`code-review`** (`/code-review`) — before any commit, as every prior ticket has done.
- **`run`** — launch backend + frontend to confirm the Reserved Budget tab shows real movement and the decline/fund story is visible.
- **`domain-modeling`** — only if the Case History three-state representation (call #4) turns out to need a new CONTEXT.md term or an ADR.
- **`frontend-design`** — for the `BudgetTimeline.tsx` decline-marker polish (judge-facing).
