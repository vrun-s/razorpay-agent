Status: resolved

# Pre-architecture readiness

## Why this exists

After `/grill-with-docs` produced `CONTEXT.md` and ADRs 0001–0005, a scratch review (`test2108.md`, repo root) assessed whether the project was ready to move into architecture planning. Verdict: the decisions made were solid, but the product itself was still underspecified in two places, plus one committed ADR rested on an unverified fact. This file tracks closing those gaps before architecture planning starts.

## Steps

1. **Resolve the decision-engine mechanism and evaluation integrity via grilling** — write them up as ADRs.
   - **Status: done.** See `docs/adr/0006-decision-engine-estimator.md` and `docs/adr/0007-evaluation-integrity.md`, plus the new `Customer Segment Proxy` term in `CONTEXT.md`.

2. **Resolve the empirical unknown behind ADR-0001** — halted-subscription recovery is committed as an MVP workflow on the assumption that Razorpay test mode lets a subscription reach `halted` fast. Nobody had confirmed this, and no test-mode account existed yet.
   - `/research` pass: **done.** See `docs/research/razorpay-test-mode-subscription-halting.md`. Razorpay's docs describe a Dashboard-only "Charge this now" button meant to force `halted` in one sitting (fail it 4x = 1 initial + 3 retries) — no API/test-card/webhook-simulator way to do it.
   - Provisioned a Razorpay test-mode account (`/wizard`): **done.** See `.scratch/pre-architecture-readiness/razorpay-setup-wizard.sh` (test mode + API keys, written to repo-root `.env`).
   - Webhook registration was originally planned as part of the wizard using `webhook.site`, but **Razorpay's dashboard blocklists that hostname** ("hostname not allowed"). Since any tunnel URL is ephemeral per-session anyway, webhook setup was moved to test time instead: `.scratch/pre-architecture-readiness/webhook_receiver.py` (local HTTP listener that prints incoming payloads) tunneled publicly via `ssh -R 80:localhost:8787 nokey@localhost.run` (no signup/install needed), URL registered as the Razorpay webhook.
   - Empirical test run: **done, result negative.** Tried on two separate test-mode subscriptions, using the correct subscriptions-specific test card (`4718 6091 0820 4366` — the generic domestic card `4111 1111 1111 1111` fails immediately with "not eligible for a mandate" and can't even authenticate a subscription). Both immediate repeated clicks and reload-spaced single clicks were tried; both invoice- and subscription-level status were checked; async lag was ruled out with a full reload after a minute's wait. The documented "Charge this now → Failure ×4 → halted" mechanism **did not reproduce** — subscriptions stayed `active` throughout. Full account in the addendum of `docs/research/razorpay-test-mode-subscription-halting.md`.
   - **Resolution**: on reflection, this was never a hard blocker for `/to-spec`. The halted-subscription *workflow itself* (HMAC signature verification, event-id dedupe, Recovery Case creation, intervention logic) only consumes a JSON payload matching Razorpay's documented `subscription.halted` webhook shape — it doesn't need Razorpay to genuinely produce one. **Decision: build and test the ingestion layer against a synthetic/hand-constructed payload matching Razorpay's documented schema, signed with our own webhook secret**, exactly as we would have needed to for fast local iteration regardless of whether live-triggering had worked. ADR-0001 stands unchanged; halted-subscription recovery stays a committed MVP workflow, not a stretch goal. The only thing actually deferred is a demo-polish question — whether to *also* show a real Razorpay-triggered halt in the final demo, or be upfront that it's simulated — and that's a low-stakes call to make later, closer to demo prep, not now. No ADR needed for the synthetic-payload approach itself: it's standard webhook-development practice, not a surprising or hard-to-reverse choice.
   - **Status: done.**

3. **Move onto the main flow** — only once step 2 is resolved (confirmed feasible, or the workflow is explicitly cut): `/to-spec` (this is a multi-session solo build), then `/to-tickets`, then `/implement` per ticket, clearing context between tickets.
   - **Status: not started.**

## Signal that this file is done

Steps 1–2 both resolved (ADRs exist; the halted-subscription assumption is confirmed or the workflow is cut) — at that point, invoke `/to-spec` and this file can be closed.

**Resolved 2026-08-22.** Both gaps are closed: ADR-0006/0007 exist, and the halted-subscription empirical question resolved to "build against a synthetic payload, keep the workflow, defer only a demo-polish detail" rather than a scope cut. Next: `/to-spec`.
