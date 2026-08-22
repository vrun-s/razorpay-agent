# 18: Dashboard — live case timeline + full demo-script observability

**What to build:** The judge-facing view from test2108.md §13 — making the system's strongest ideas visible instead of implicit.

**Blocked by:** 09, 10, 15

**Status:** ready-for-agent

- [ ] A live case timeline view shows, for a selected case: detected → decision + reasoning → policy check (naming the specific constraint that bound it) → execution → webhook → reassessment → stop, each with a timestamp.
- [ ] A view shows the Reserved Budget as a moving quantity over the course of a run.
- [ ] At least one `NO_ACTION` case that still recovered is identifiable/highlighted in the dashboard.
- [ ] At least one policy rejection is visible/browsable in the dashboard.
- [ ] At least one human-overridden escalation is visible/browsable in the dashboard.
- [ ] An aggregate view shows Net Recovered Revenue vs. both baselines with a confidence interval and % of offline-optimal, sourced from ticket 15's evaluation harness output.
- [ ] The calibration curve from ticket 15 is displayed in the dashboard.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
