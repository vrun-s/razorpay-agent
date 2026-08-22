# 09: Escalation queue + human override

**What to build:** A real destination for escalated cases — a dashboard queue where a human can act, with that action folded back into the one audit trail.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] An `Escalated` case state exists, set when ticket 08's LLM escalation flag fires or a Policy Engine escalation threshold is crossed.
- [ ] The dashboard shows a queue of `Escalated` cases, each displaying full Case History and the LLM's reasoning for the flag.
- [ ] From this queue, a human can override the case with their own chosen `Intervention`.
- [ ] From this queue, a human can instead manually resolve/close the case.
- [ ] A human's override or resolution is written into Case History using the same shape as any other intervention/outcome entry — no side channel.
- [ ] Test/manual check: a case flagged escalation-worthy appears in the queue.
- [ ] Test/manual check: an override action updates case state and Case History correctly.
- [ ] Test/manual check: a manual resolve closes the case and records the resolution.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
