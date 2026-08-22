# 05: Policy Engine — real constraints + rejection audit

**What to build:** Replace ticket 01's pass-through Policy Engine stub with real, merchant-defined constraint enforcement, and make rejections visible in the audit trail rather than silently substituted.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] The Policy Engine validates a proposed `Intervention` against: `max_discount`, `max_payment_retries`, `max_interventions_per_customer`, and a `recovery_budget` ceiling.
- [ ] A proposal violating any single constraint is rejected outright (not downgraded/auto-corrected to a compliant value).
- [ ] Every rejection is recorded on the case's audit trail: which constraint was violated and what was originally proposed.
- [ ] A compliant proposal passes through unchanged.
- [ ] Test: one test per constraint proving it actually blocks a violating proposal.
- [ ] Test: a compliant proposal passes through unmodified.
- [ ] Test: a rejected proposal's audit entry names the specific constraint and the rejected value.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
