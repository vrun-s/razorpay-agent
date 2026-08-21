# Trigger reassessment on real webhooks and on response-window timeouts, not webhooks alone

Once a case is a persistent sequence ([[0004-cases-as-sequences]]), something has to decide when the agent looks at it again. Reacting only to real Razorpay webhooks is the natural default given the rest of the system is event-driven, but it has a blind spot: a customer who simply goes silent — never retries, never responds to a reminder or payment link — produces no webhook at all. Track 3 explicitly names "promise-to-pay tracking" as a workflow, which is impossible to express if silence is invisible to the system; the case would just sit there forever waiting for an event that never comes.

**Decision**: Reassessment is triggered two ways — immediately on a real, outcome-relevant webhook (e.g. a payment succeeding closes the case as recovered right then), and on a scheduled sweep that catches timeouts: if a case's current intervention hasn't produced an outcome within its expected response window, the absence of a response is itself treated as a trigger to reassess.

**Consequences**: Requires a scheduled sweep mechanism alongside webhook handlers, not just webhook handlers alone — genuine added infrastructure, not free. In exchange, silence becomes a real signal the agent can act on, which is what makes escalation and stopping rules meaningful rather than decorative.
