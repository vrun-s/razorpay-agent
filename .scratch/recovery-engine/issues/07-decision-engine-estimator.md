# 07: Decision Engine — Beta-Bernoulli estimator + customer_segment_proxy

**What to build:** Replace ticket 01's fixed-rule decision with the real per-cell Bayesian estimator from [[0006-decision-engine-estimator]]. Must not start until ticket 02 (simulator generator) is complete, per [[0007-evaluation-integrity]]'s construction-time independence rule.

**Blocked by:** 02, 06

**Status:** ready-for-agent

- [ ] `customer_segment_proxy` is computed deterministically from observable Customer History fields (order count, average order value, payment-reliability rate) via fixed thresholds — no LLM involvement in this computation.
- [ ] A Beta-Bernoulli posterior exists per `(failure_reason × customer_segment_proxy × intervention)` cell, initialized from a flat `Beta(2,2)` cold-start prior.
- [ ] The posterior updates online (`α += 1` on success, `β += 1` on failure) only for cases sourced from the synthetic simulation stream (source-tagged `simulated`).
- [ ] A case tagged `real` never updates the posterior, per the simulator↔Razorpay execution boundary.
- [ ] The estimator's interface exposes both a point estimate and an explicit uncertainty measure (e.g. credible interval width) for a given cell.
- [ ] This estimator replaces ticket 01's fixed-rule decision as the actual decision source consumed by the case lifecycle from ticket 06.
- [ ] Test: the posterior updates correctly on a simulated success and a simulated failure.
- [ ] Test: `customer_segment_proxy` produces the correct bucket for representative Customer History inputs at each threshold boundary.
- [ ] Test: a `real`-tagged outcome does not change the posterior for its cell.
- [ ] Test: the uncertainty measure narrows as more observations accumulate in a cell.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
