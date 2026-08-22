# 02: Synthetic Merchant Simulator — response-curve generator (design freeze)

**What to build:** The Synthetic Merchant Simulator's response-curve generator, written and frozen in full as a standalone artifact — persona mix, response curves per intervention, and fatigue decay logic — before any Decision Engine work begins. This must be built with zero visibility into the estimator's design, per [[0007-evaluation-integrity]]'s independence discipline; if AI-assisted, do this in a session/context that never sees ticket 07's work.

**Blocked by:** None (can start immediately; must complete before ticket 07 starts)

**Status:** ready-for-agent

- [ ] Persona mix (e.g. loyal, bargain hunter, new, unreliable payer — per `Customer Segment` in CONTEXT.md) is implemented as pure, deterministic-given-a-seed logic.
- [ ] Each persona's response curve (recovery probability per intervention) is fully specified and versioned in one frozen module.
- [ ] Fatigue/diminishing-returns decay logic (probability decay across repeated interventions within a case) is implemented.
- [ ] Per-case hidden ground truth (`Customer Segment`, per-case outcome odds per intervention) is generated and documented as simulator-only — explicitly marked never to be exposed to the Decision Engine, per CONTEXT.md's `Customer Segment` vs `Customer Segment Proxy` distinction.
- [ ] This module has no import from, and is not imported by, any Decision Engine code (nothing from ticket 07 exists yet, so this should be trivially true — verify no accidental coupling).
- [ ] A standalone test proves the generator produces reproducible output for a fixed seed (same seed → same generated cases and outcomes).
- [ ] Not yet wired into the Gateway seam or any live endpoint — that integration is ticket 14.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
