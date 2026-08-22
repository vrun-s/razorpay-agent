# 17: Real-Razorpay integration-proof slice (~20–25 cases)

**What to build:** Prove the integration mechanics are genuinely real, not just simulated — a small, deliberately bounded slice executed through actual Razorpay test mode.

**Blocked by:** 13

**Status:** ready-for-agent

- [ ] A small, hand-picked set of roughly 20–25 cases runs through the real-Razorpay-backed executor from ticket 13.
- [ ] The slice stays within Razorpay's 30-Payment-Link-per-business test-mode cap.
- [ ] Every case in this slice is tagged `real` in Case History and is confirmed excluded from the Decision Engine's posterior updates, per ticket 07's exclusion rule.
- [ ] At least one case in the slice exercises the failed-payment workflow (Payment Link) and at least one exercises the halted-subscription workflow (Resume Charge).
- [ ] Manual/integration verification: the Razorpay dashboard shows the payment links / resume-charge attempts corresponding to this slice.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
