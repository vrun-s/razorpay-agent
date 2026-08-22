# 11: Evaluation metric & baselines contract

**What to build:** A short, explicit written pin-down of the evaluation design, resolved before the evaluation harness (ticket 15) is built — so there's no ambiguity to improvise on the fly.

**Blocked by:** None (can start immediately; must complete before ticket 15 starts)

**Status:** ready-for-agent

- [ ] A written document states the primary metric: Net Recovered Revenue (gross recovered minus incentive cost) — not raw recovery rate.
- [ ] The document names the two baselines: no-intervention, and a fixed-rule blanket 5% discount.
- [ ] The document states the comparison method: a paired counterfactual replay — the same case stream, under a shared RNG seed, run through no-intervention, fixed-rule, AI treatment, and offline-optimal.
- [ ] The document states the reporting method: a bootstrap confidence interval on the AI-vs-baseline gap, not a bare point estimate.
- [ ] The document states the dataset split sizes (300 dev / 150 validation / 200 held-out synthetic cases) and that the held-out set is never tuned on.
- [ ] Ticket 15's implementation references this document directly rather than re-deriving any of the above.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
