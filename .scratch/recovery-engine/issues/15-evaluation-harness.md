# 15: Evaluation harness — paired counterfactual replay + CI + calibration

**What to build:** The actual headline measurement, implementing exactly what ticket 11's contract specifies — no re-deriving the design here.

**Blocked by:** 11, 14

**Status:** ready-for-agent

- [ ] Generates the 300 dev / 150 validation / 200 held-out synthetic case splits per [[0007-evaluation-integrity]], using ticket 14's simulator integration.
- [ ] Runs the paired counterfactual replay: the same case stream, under a shared RNG seed, across no-intervention, fixed-rule (5% discount), AI treatment, and a retrospective offline-optimal computation.
- [ ] Computes Net Recovered Revenue and Incremental Recovery per arm.
- [ ] Reports a bootstrap confidence interval on the AI-vs-baseline gap.
- [ ] Computes and outputs a calibration curve (predicted vs. actual recovery probability) for the estimator.
- [ ] The held-out set is never used to tune anything — no code path feeds held-out results back into the estimator's parameters.
- [ ] Test: rerunning the harness with the same seed reproduces the same headline numbers (determinism check).
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
