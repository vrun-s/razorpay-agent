# 13: Executor/Gateway seam — real Razorpay + simulator-backed implementations

**What to build:** Concrete implementations behind the Gateway interface fixed in ticket 01/03. The interface itself does not change here — only new implementations are added behind it.

**Blocked by:** 10, 12

**Status:** ready-for-agent

- [ ] A real Razorpay-backed implementation of `create_payment_link` and `resume_charge` exists, using the exact interface fixed in ticket 01/03.
- [ ] A simulator-backed fake implementation of the same interface exists (may extend ticket 01's stub).
- [ ] Both implementations are swappable via configuration; no code outside the Executor module branches on which one is active.
- [ ] Real calls run against Razorpay test-mode credentials from `.env`.
- [ ] Test: a contract test runs against both implementations, asserting they satisfy the same interface behavior (return shape, error handling).
- [ ] Manual/integration check: a real `create_payment_link` call succeeds against Razorpay test mode.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
