# 06: Case lifecycle — reassessment loop, Case History, fatigue, stop

**What to build:** Turn the Recovery Case from a one-shot decision into a persistent, multi-step sequence per [[0004-cases-as-sequences]] and [[0005-hybrid-reassessment-trigger]].

**Blocked by:** 04, 05

**Status:** ready-for-agent

- [ ] A Recovery Case can undergo multiple Reassessments over its lifetime rather than resolving after one decision.
- [ ] Reassessment triggers on a real, outcome-relevant webhook (e.g. the underlying payment succeeds) — fires immediately, not on the next sweep.
- [ ] Reassessment also triggers on a scheduled sweep when a case's Response Window has elapsed with no outcome — silence is itself a trigger.
- [ ] Case History accumulates every intervention and its outcome, in order, for the life of the case.
- [ ] A fatigue/diminishing-returns effect is applied based on Case History (repeating the same intervention on a case yields a visibly reduced expected effect vs. the first attempt).
- [ ] A case can reach an explicit `Stop` state when further intervention isn't economically justified, with the reasoning recorded.
- [ ] Policy-derived sequence-length bounds (`max_payment_retries`, `max_interventions_per_customer`) are enforced as hard stops — a case cannot loop past them regardless of what the decision step recommends.
- [ ] Test: a case exceeding `max_payment_retries` is force-stopped.
- [ ] Test: a webhook-triggered reassessment fires immediately upon a relevant event.
- [ ] Test: a scheduled-sweep reassessment fires after the Response Window elapses with no outcome.
- [ ] Test: repeating an intervention shows a measurably reduced expected effect via the fatigue logic.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
