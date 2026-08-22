# 03: Architecture freeze — lock core interfaces

**What to build:** A deliberate checkpoint, before the project gets more complex, that reviews and locks the shapes every later ticket depends on. This is primarily a documentation/review deliverable, not new code.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] A written note (a CONTEXT.md addition or a short new ADR) documents the locked Recovery Case schema (fields as they exist after ticket 01).
- [ ] The note documents the shared `Intervention` type and confirms which subsets are valid per workflow (failed-payment vs halted-subscription), per [[0002-pluggable-workflow-abstraction]].
- [ ] The note documents the Gateway/Executor interface signature fixed in ticket 01 (`create_payment_link`, `resume_charge`, webhook parsing).
- [ ] The note documents the intended Policy Engine contract (what `validate()` takes and returns, including the rejection shape).
- [ ] The note documents the intended Decision Engine interface (inputs it will consume, outputs it will produce: point estimate + uncertainty measure) ahead of ticket 07's implementation.
- [ ] The note explicitly states these five shapes are locked and should not change from ticket 04 onward without a deliberate, documented decision.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
