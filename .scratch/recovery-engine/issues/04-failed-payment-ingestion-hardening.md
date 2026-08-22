# 04: Failed-payment webhook ingestion hardening

**What to build:** Real signature verification and deduplication for the `payment.failed` ingestion path, replacing ticket 01's unverified stub endpoint.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] Incoming `payment.failed` webhooks are verified via HMAC-SHA256 over the raw request body using the webhook secret; a payload with an invalid signature is rejected and never creates or mutates a case.
- [ ] Incoming events are deduplicated by `x-razorpay-event-id`; a repeated event id is a no-op (no duplicate case, no double-applied outcome).
- [ ] A hand-constructed synthetic payload matching Razorpay's documented `payment.failed` schema, correctly signed, is accepted and creates a case (this is the pattern already proven this session for `subscription.halted` — reuse it).
- [ ] A malformed or incomplete payload is rejected with a clear error, not silently accepted as a partial case.
- [ ] Test: a validly-signed synthetic payload is accepted.
- [ ] Test: an invalidly-signed payload is rejected.
- [ ] Test: replaying the same `x-razorpay-event-id` does not create a second case.
- [ ] Test: a malformed payload is rejected.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
