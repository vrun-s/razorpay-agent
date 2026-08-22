# 10: Streaming Allocator — Recovery Budget + Reserved Budget

**What to build:** Real online, arrival-order budget allocation per [[0003-streaming-allocation]], replacing any implicit "always fund" assumption from earlier tickets.

**Blocked by:** 06, 07

**Status:** ready-for-agent

- [ ] Cases are processed one at a time in arrival order — the allocator never has access to cases that haven't arrived yet when deciding on the current one.
- [ ] A Recovery Budget is tracked with a Reserved Budget portion deliberately withheld against the expectation that better-value cases may still arrive.
- [ ] The allocator can decline to fund a mediocre case (using the estimator's point estimate + uncertainty from ticket 07) rather than spending eagerly.
- [ ] The budget ledger distinctly tracks spent, available, and reserved amounts at any point in time.
- [ ] A deterministic test sequence demonstrates the reserve mechanism concretely: a mediocre case is declined, and a later, better case in the same run is funded.
- [ ] Test: reserve-withholding logic behaves correctly against a small, fixed case sequence with known expected values and uncertainty.
- [ ] Test: budget ledger arithmetic (spent/available/reserved) is correct across a sequence of allocation decisions.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
