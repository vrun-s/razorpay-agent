# 12: Halted-subscription workflow added

**What to build:** Prove [[0002-pluggable-workflow-abstraction]] for real by adding the second workflow, reusing the entire engine matured on failed-payment (tickets 04–10) rather than building a parallel bespoke pipeline.

**Blocked by:** 09, 10

**Status:** ready-for-agent

- [ ] A `subscription.halted` detector creates a Recovery Case using the same case store, lifecycle, Policy Engine, Decision Engine, Allocator, and Escalation queue as the failed-payment workflow — no separate pipeline.
- [ ] `subscription.halted` ingestion is hardened the same way ticket 04 hardened `payment.failed`: real HMAC-SHA256 verification and `x-razorpay-event-id` dedupe.
- [ ] A hand-constructed synthetic payload matching Razorpay's documented `subscription.halted` schema, correctly signed, is accepted and creates a case — reusing the pattern already proven empirically this session.
- [ ] `Resume Charge` is the only workflow-valid `Intervention` exposed for halted-subscription cases; `Payment Retry` is never offered as an option here.
- [ ] The reverse restriction also holds: `Resume Charge` is never valid for a failed-payment case.
- [ ] Test: a synthetic `subscription.halted` payload creates a case and flows through the full existing engine.
- [ ] Test: a `Payment Retry` proposal is rejected as invalid for a halted-subscription case.
- [ ] Test: a `Resume Charge` proposal is rejected as invalid for a failed-payment case.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
