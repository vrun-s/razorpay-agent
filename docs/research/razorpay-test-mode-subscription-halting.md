# Can Razorpay test mode reach `halted` subscription status faster than production?

## Direct answer

**Yes — partially, via a documented Dashboard feature, not a raw API call or special test card.** Razorpay's official "Test Subscriptions" documentation describes a **"Charge this now"** button, available only in test mode, that lets a developer manually trigger a subscription's due charge on demand and choose whether it succeeds or fails — instead of waiting for the real billing date. Each simulated failure advances the retry counter, and "the next charge time is updated by a single day, rather than the actual plan period." Failing four simulated charges in a row (the initial attempt plus three retries) exhausts all retries and moves the subscription to `halted` immediately — no multi-day wait required. ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/)) This is a Dashboard-only manual action, however; the docs do not expose a corresponding public API endpoint or a special test card number that does the same thing, and there is no way to skip straight to `halted` in one call. The production retry ladder itself (3 retries over ~4 calendar days) is real and documented, and is what test mode's manual clicks are compressing.

---

## 1. Can the retry schedule be compressed, forced, or manually triggered in test mode?

Yes, but only through one specific documented mechanism: the Dashboard's **"Charge this now"** button on a due test-mode subscription. Quoting the docs: "In test mode, you can simulate these charges from the Dashboard using the Charge this now button" and "the test charge option prompts you to choose the result of a manual charge attempt" — success or failure. ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/))

This is explicitly test-mode-only: "A test charge on a Subscription can be triggered only in test mode." ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/))

There is no documented raw API endpoint for this specific "test charge" action (only the Dashboard button is documented), and no webhook-simulation tool that can substitute for it: the general webhook-testing tool ("Validate and Test Webhooks") fires test webhooks only for transactions that actually happened in test mode (payments and payouts), and does not mention subscription events like `subscription.halted`/`subscription.pending` as separately simulable. Quoting that page: "Test events get triggered on a transaction done in the Test mode." ([Validate and Test Webhooks](https://razorpay.com/docs/webhooks/validate-test/)) So the only lever is the Dashboard manual-charge button, not the webhook simulator and not a raw API call.

Separately, there is also an "Attempt Charge" manual-retry action for invoices stuck in `issued` state (available in both test and live mode), but the docs explicitly note this is a *different* mechanism that **does not** advance the retry ladder: "A manual charge attempt does not count toward the remaining retries for a Subscription." ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/)) Only the test-mode "Charge this now" simulated-failure path counts toward exhausting retries.

## 2. Or does test mode just replay the same multi-day retry ladder as production, with no way to accelerate it?

No — this is not the case. Test mode does not force you to wait through the real T+1/T+2/T+3 day cadence. Instead of waiting for the actual due date, the manual "Charge this now" button lets you fire the due charge (and its subsequent retries) back-to-back, and "the next charge time is updated by a single day, rather than the actual plan period" shown in the docs' own example of a subscription on a longer (e.g. two-month) billing cycle. ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/)) In other words, test mode's retry *counting* logic is the same (still requires exhausting the same number of retries), but the *waiting* is removed — you can click through all four failed attempts in one sitting rather than over ~4 real days.

## 3. Are there documented test cards, sandbox behaviors, or API parameters specifically for testing the `halted` state without waiting days?

Partially documented, and it is a dashboard behavior rather than a special test card:

- No special "auto-fail" test card number specific to subscriptions was found. General test-card documentation only describes generic ways to fail a payment during checkout (e.g., "Enter a random OTP below 4 digits to fail the payment"), not anything subscription-retry-specific. ([Test Card Details](https://razorpay.com/docs/payments/payments/test-card-details/))
- A real sandbox constraint exists that affects subscription testing timing: "In test mode, you can perform a subsequent debit only within 3 days of token creation, as card tokens are valid for 3 days only." ([Test Card Details](https://razorpay.com/docs/payments/payments/test-card-details/)) This matters because it caps how long a test subscription's saved card token remains usable for automatic retries — independent of, but interacting with, the manual test-charge mechanism above.
- The documented, purpose-built mechanism for reaching `halted` without waiting is the "Charge this now" button covered in Q1/Q2: "If you fail a charge 4 times in a row, all the available retries get exhausted. This results in a Subscription being marked as `halted`." ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/))
- Once a subscription is `halted` in test mode, the Dashboard UI itself changes to reflect it: "the Charge This Now button available on Dashboard is replaced with an Issue Invoice button for `halted` subscriptions," and using it "issues a new invoice, but a charge is not attempted on the saved card." ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/))
- One testing caveat: performing test charges blocks separate testing of the update-subscription flow — "You cannot test the update subscription feature if any test charges (beyond the initial authentication payment) have been made." ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/))

## 4. What are the exact retry intervals/schedule? Confirm or correct the "3 times over ~4 days" figure.

**The prior doc's figure is confirmed as documented**, with one added nuance about how the count is phrased:

- Retry timing for card-based subscriptions: "We automatically retry the payment on the following day" (T+1); "If the charge fails again, we automatically reattempt the charge two more times on T+2 and T+3 days, respectively." ([Payment Retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/), confirmed via search-indexed page text)
- Total retries before halting: "When a Subscription is moved to the `halted` state post 3 retry attempts of payment failure..." ([Subscriptions | Notifications](https://razorpay.com/docs/payments/subscriptions/notifications/))
- Outcome: "If the payment fails after all retries, the Subscription will move to the `halted` state." ([Payment Retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/))
- The test-mode doc phrases the same threshold from the other end — counting the original failed charge plus its 3 retries as "4 times in a row" — which is consistent, not contradictory: 1 initial failed charge + 3 retries (T+1, T+2, T+3) = 4 total failed charge attempts spanning the original day through T+3 (≈4 calendar days). ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/))
- This matches the ADR's/prior-doc's claim of "3 times over ~4 days" — that figure is corroborated by primary sources, not merely a secondary-source guess.
- Retry timing differs by payment method: e-mandate retries only happen after 24+ hours following bank confirmation/rejection, and shift around bank holidays ("If the charge day (T) is a bank holiday, we will charge on T-1 days. If the charge day (T) and the previous day (T-1) are bank holidays, we will charge on T-3 days."); UPI Autopay lets the customer switch payment method instead of a fixed auto-retry. ([Payment Retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/)) So the "3 times over ~4 days" figure specifically describes **card-based** auto-debit retries — the docs do not state that e-mandate/UPI follow the identical cadence.
- Lifecycle: `created` → `authenticated` → `active` → (on auto-charge failure) `pending` → (after all retries exhausted) `halted`; `halted` → `active` only if the customer authenticates a new card or an unpaid invoice is later successfully charged. ([Subscriptions States](https://razorpay.com/docs/payments/subscriptions/states/), [Payment Retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/))
- Once `halted`, invoices keep generating on schedule but auto-charge is not attempted: "Invoices for such Subscriptions are still created. However, we will not charge these invoices. You will have to charge them manually." ([Payment Retries](https://razorpay.com/docs/payments/subscriptions/payment-retries/))
- Documentation does not specify whether the retry count (3) or interval (1 day) is merchant-configurable; no configuration parameter for this was found in the Subscriptions API reference pages consulted.

## 5. Is there a way to directly transition a subscription to `halted` via API, independent of the retry ladder?

**Documentation does not specify any such endpoint — none was found.** Specifically:

- The Pause Subscription API only produces a `paused` status (or `cancelled` if the subscription was still `authenticated`); nothing about `halted`. ([Pause a Subscription](https://razorpay.com/docs/api/payments/subscriptions/pause-subscription/))
- The Cancel Subscription API only produces a `cancelled` status, immediately or at cycle end via `cancel_at_cycle_end`; cancelled and halted are documented as distinct, unrelated terminal/interruption states. ([Cancel a Subscription](https://razorpay.com/docs/api/payments/subscriptions/cancel-subscription/))
- The Update Subscription API explicitly cannot be used on a subscription already in `pending` or `halted` state ("Subscriptions in the created, pending or halted state cannot be updated"), which further indicates `halted` is not something the Update endpoint can set or clear. ([Update a Subscription](https://razorpay.com/docs/payments/subscriptions/update/))
- No admin/test-only "set status" endpoint was found anywhere in the Subscriptions API reference pages consulted.
- The only documented way to reach `halted` faster than the real calendar days is the test-mode Dashboard "Charge this now" simulated-failure flow described in Q1–Q3 — which still walks through (a compressed version of) the retry ladder rather than skipping it via a direct API call.

---

## Addendum: empirical result (2026-08-22) — the documented mechanism did not reproduce

Hands-on testing in a live Razorpay test-mode dashboard did **not** match the "Charge this now" behavior described above:

- Using the correct subscriptions-specific test card (`4718 6091 0820 4366`, the domestic Visa card from the "Test Cards for Subscriptions" table — the generic `4111 1111 1111 1111` domestic card fails immediately with "This card is not eligible for a mandate" and cannot even authenticate a subscription), a subscription was authenticated successfully and reached `active`.
- On a first subscription, clicking **Charge this now → Failure** four times in immediate succession did not produce a `halted` (or even `pending`) status; the subscription remained `active`, and — unexpectedly — several of the subsequent invoices later showed as `Paid` despite `Failure` having been explicitly selected each time.
- On a **second, freshly created** subscription (to rule out corrupted state from the first), a single **Charge this now → Failure** click left the subscription `active` and the invoice in `Issued` (the normal pre-charge state, not a distinct "Failed" badge — the dashboard does not appear to expose a failed-invoice badge separately from "Issued"). The status did not change even after a full page reload and a ~1 minute wait (ruling out simple async/background-job lag).
- Conclusion: as observed, the documented "fail 4 times → `halted`" Dashboard mechanism is **not reliably reproducible** in practice. Either the current live dashboard behavior has diverged from the docs, the mechanism requires an undocumented precondition/sequence not captured above, or it is simply unreliable. Given the effort already invested (two subscriptions, immediate and reload-spaced clicks, both invoice- and subscription-level status checked), further trial-and-error against the live dashboard is not a good use of a 15-day solo build's time.
- This does not contradict the earlier documented-answer sections above — those remain an accurate summary of what Razorpay's docs *say* — but it means ADR-0001's halted-subscription workflow **cannot currently be assumed testable on-demand via this route**, and the fallback options noted in `.scratch/pre-architecture-readiness/spec.md` (inject synthetic `subscription.halted` events, or demote the workflow to a stretch goal) should be considered live options, not just a theoretical contingency.

## Addendum 2 (2026-09-03) — the documented mechanism *did* reproduce

A second hands-on attempt succeeded where the 2026-08-22 one did not, matching the docs.

- Same subscriptions-specific test card (`4718 6091 0820 4366`).
- Three consecutive **Charge this now → Failure** clicks left the subscription `active`; the
  **fourth** Failure transitioned it **`active` → `halted`** directly (no `pending` badge
  observed in between). This is exactly the documented "fail 4 times in a row → `halted`"
  behaviour. ([Test Subscriptions](https://razorpay.com/docs/payments/subscriptions/test/))
- **Not verified this run:** whether a `subscription.halted` **webhook was actually delivered**
  to a registered endpoint. Only the Dashboard status transition was observed. The end-to-end
  path we actually depend on (Razorpay fires `subscription.halted` → `/webhooks/subscription-halted`
  → case created) is still unconfirmed against real Razorpay.
- What differed from the 2026-08-22 failure is not established (transient Dashboard issue then,
  or a click sequencing/timing difference). Treat the mechanism as **reproducible but historically
  finicky**: the `halted` *state* is reachable on demand in test mode; one clean confirmation of
  real `subscription.halted` *webhook delivery* is still owed before the workflow's real trigger
  can be called proven.
- Net: the "inject synthetic `subscription.halted` events" fallback is still what the shipped
  build uses, but it is now a *convenience*, not a *necessity* — a real-Razorpay halted slice is
  viable. See `.scratch/recovery-engine/issues/20-real-razorpay-halted-subscription-slice.md`.

## Sources

Primary (Razorpay official docs), consulted directly via WebFetch or confirmed via search-engine indexing of the page:

- https://razorpay.com/docs/payments/subscriptions/payment-retries/
- https://razorpay.com/docs/payments/subscriptions/states/
- https://razorpay.com/docs/payments/subscriptions/test/
- https://razorpay.com/docs/subscriptions/test-guide/ (redirects to / mirrors the same content as `/docs/payments/subscriptions/test/`)
- https://razorpay.com/docs/webhooks/subscriptions/
- https://razorpay.com/docs/payments/subscriptions/notifications/
- https://razorpay.com/docs/api/payments/subscriptions/pause-subscription/
- https://razorpay.com/docs/api/payments/subscriptions/cancel-subscription/
- https://razorpay.com/docs/payments/subscriptions/update/
- https://razorpay.com/docs/payments/payments/test-card-details/
- https://razorpay.com/docs/webhooks/validate-test/
- https://razorpay.com/docs/subscriptions/faqs/ (checked — no retry/halting content found on this page)

Secondary sources used only as leads to locate the above primary pages (not cited for any claim):

- https://www.svix.com/blog/reviewing-razorpay-webhook-docs/
- https://www.frugaltesting.com/blog/how-to-test-subscription-workflows-in-razorpay-and-paypal-like-fintech-platforms
- https://www.chargebee.com/docs/payments/2.0/kb/billing/how-to-test-card-upi-payments-via-razorpay-with-chargebee-integration
- GitHub search hit: frappe/erpnext PR #26564 (non-Razorpay, ERPNext-specific; confirmed Razorpay itself has no such endpoint)
