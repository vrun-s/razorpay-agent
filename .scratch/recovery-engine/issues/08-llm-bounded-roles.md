# 08: LLM-bounded roles — diagnosis, narration, escalation flagging

**What to build:** Wire the LLM into its three fixed, bounded jobs per [[0006-decision-engine-estimator]] — and nothing beyond them.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] An LLM call diagnoses `failure_reason` from unstructured decline text or bank codes, mapping to one of the Decision Engine's known `failure_reason` categories.
- [ ] An LLM call generates the natural-language justification attached to each Reassessment's decision in the audit trail.
- [ ] An LLM call flags a case as escalation-worthy based on qualitative signal (e.g. an angry or confused customer response), independent of any numeric policy threshold.
- [ ] The recovery-probability value used for a decision is provably unchanged by any LLM step — it always matches the estimator's own posterior output from ticket 07.
- [ ] Test: representative example decline texts map to the correct `failure_reason` category.
- [ ] Test: a Reassessment's audit entry contains a generated justification string, not just the raw numbers.
- [ ] Test: a crafted qualitative-signal example triggers the escalation flag.
- [ ] Test: asserts the probability value consumed by the case lifecycle is bit-for-bit the estimator's value, not something the LLM step could have altered.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
