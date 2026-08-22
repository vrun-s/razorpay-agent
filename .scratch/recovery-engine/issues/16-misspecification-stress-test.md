# 16: Misspecification stress test

**What to build:** The robustness check from [[0007-evaluation-integrity]] that guards the headline number against being fragile to the simulator's exact assumptions.

**Blocked by:** 15

**Status:** ready-for-agent

- [ ] The simulator's persona mix is perturbed by roughly ±20% in one scenario run.
- [ ] The simulator's response-curve elasticities are perturbed by roughly ±20% in a second scenario run.
- [ ] The simulator's fatigue decay rate is perturbed by roughly ±20% in a third scenario run.
- [ ] The full paired evaluation from ticket 15 is rerun, unchanged, against each perturbed scenario.
- [ ] **Explicit criterion: no retuning of the estimator's priors, features, or hyperparameters between perturbation scenarios** — the exact same trained/fitted estimator configuration from ticket 15 is evaluated as-is against each perturbed variant.
- [ ] The AI-vs-baseline lift is checked for survival (remains positive/significant per ticket 15's CI methodology) in at least 2 of the 3 perturbation scenarios.
- [ ] The result is reported either way — a failed stress test is documented, not hidden.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
