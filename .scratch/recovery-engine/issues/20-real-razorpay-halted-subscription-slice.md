# 20: Real-Razorpay halted-subscription slice (close ticket 17's open half)

**What to build:** One clean end-to-end proof that the halted-subscription workflow works against
real Razorpay test mode, not just synthetic events — the half of ticket 17 deliberately left
open. Small and bounded, like ticket 17's failed-payment slice. Not an evaluation input (every
case tagged `real`, excluded from the estimator per ticket 07).

**Context:** As of 2026-09-03 the `active → halted` transition *is* reproducible in test mode
("Charge this now → Failure" ×4 on the subscriptions test card `4718 6091 0820 4366`; the fourth
failure flips `active → halted` directly). What is *not* yet confirmed is that Razorpay then
delivers a `subscription.halted` **webhook** to a registered endpoint. See
`docs/research/razorpay-test-mode-subscription-halting.md` (Addendum 2) and the memory note
`project-ticket17-pending-manual-execution`.

**Blocked by:** none new — ticket 13 (real executor) and ticket 17 (failed-payment slice, its
tunnel/webhook-registration setup) are done. This is the follow-on the 2026-08-27 close of
ticket 17 punted "until the user reports the subscription actually reached `halted`."

**Status:** ready-for-agent

## Acceptance criteria

- [ ] A real test-mode subscription is driven to `halted` via "Charge this now → Failure" ×4
      (card `4718 6091 0820 4366`), and the `active → halted` transition is confirmed in the
      Razorpay dashboard.
- [ ] The webhook tunnel from ticket 17 (`ssh -R … localhost.run`, URL re-registered in the
      Razorpay dashboard) is live, subscribed to `subscription.halted`, with the secret matching
      `RAZORPAY_WEBHOOK_SECRET`.
- [ ] The `subscription.halted` webhook is **received** at `/webhooks/subscription-halted`:
      capture the raw payload, confirm HMAC-SHA256 signature verification passes, and confirm the
      payload shape matches `webhooks.py::_extract_*` (record any field-shape mismatch vs the
      synthetic payload ticket 12 hand-built).
- [ ] The webhook creates exactly one `RecoveryCase` (`workflow_type=HALTED_SUBSCRIPTION`,
      `source=EventSource.REAL`), with `x-razorpay-event-id` dedupe working on a replayed delivery.
- [ ] The case runs one decision cycle. `RESUME_CHARGE` is the only workflow-valid intervention.
      **Known risk (from the ticket-17 memory):** `decide()` may pick `NO_ACTION` if the
      estimator's `(…, resume_charge)` cell hasn't left cold start, and Razorpay's API may reject
      `resume_charge` against a subscription that is not in a resumable state — record whatever
      actually happens rather than forcing a green result.
- [ ] Stay within the 30-Payment-Link / test-mode caps; mind the 3-day card-token validity and
      test-mode 429 rate-limiting noted in the ticket-17 memory.
- [ ] Findings written up: append a short result section to
      `docs/research/razorpay-test-mode-subscription-halting.md`, and update the
      `project-ticket17-pending-manual-execution` memory. If the real trigger is fully proven,
      soften the remaining "webhook delivery unconfirmed" hedges in `README.md`.
- [ ] Any code changes (payload-shape fixes in `webhooks.py::_extract_*`, etc.) committed before
      moving on. Per repo convention, do **not** tick ticket 17's checkbox in its file — track
      completion via commit/handoff/memory.

## Out of scope

- Evaluation numbers (this slice never feeds the estimator or the harness).
- The learnable discount-sensitivity model ([[0014-flat-incentive-response-learnable-deferred]]).
- Making `RESUME_CHARGE` reliably chosen — if the estimator/API blocks a clean recovery, that is
  itself a documented finding, same disposition as ticket 17's failed-payment gaps.
