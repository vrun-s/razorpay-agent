# Design the recovery engine for pluggable workflow types from day one

Only two workflows ship initially — failed-payment recovery and halted-subscription recovery — but checkout abandonment ([[0001]]) and receivables/invoice chasing are both plausible additions later if time allows. Retrofitting a shared engine after two workflows are already hardcoded tends to be expensive: workflow-specific assumptions about detection signals and action sets leak into what should be shared logic once there's no abstraction forcing them apart.

**Decision**: The core loop (detect → decide → policy → execute → verify → attribute) is built against a workflow abstraction from the start. A new revenue-loss type plugs in its own detector and action set, and reuses the shared decision engine, policy engine, and measurement/attribution layer — rather than each workflow being a separately-wired, bespoke pipeline.

**Consequences**: Slightly more upfront design cost to make two workflows share one engine, in exchange for a materially cheaper path to a third or fourth workflow later.
