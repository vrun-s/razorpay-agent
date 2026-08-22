# 01: Tracer-bullet scaffold + Gateway interface contract

**What to build:** A thin but complete end-to-end path for the failed-payment workflow, with every layer deliberately stubbed except the interfaces that later tickets will build against. This proves the whole loop connects before any real intelligence exists, and fixes the Gateway/Executor interface shape so nothing downstream has to redesign it later.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] FastAPI backend and React frontend scaffolds exist and run locally.
- [ ] A Recovery Case store exists (in-memory or a simple DB) with at minimum: id, workflow type, status, and an ordered Case History.
- [ ] A stable Gateway/Executor interface is defined (e.g. a Protocol/ABC) with methods covering `create_payment_link`, `resume_charge`, and webhook payload parsing — this exact shape is what tickets 03 and 13 build against; it must not need to change later.
- [ ] A fake/stub implementation of the Gateway interface exists and makes no real Razorpay calls.
- [ ] One endpoint accepts a synthetic `payment.failed`-shaped payload and creates a Recovery Case (signature verification is out of scope here — that's ticket 04).
- [ ] A trivial fixed-rule decision runs on the new case (e.g. always propose `Payment Retry`).
- [ ] A pass-through Policy Engine stub lets the decision through unmodified (real constraints are ticket 05).
- [ ] The fake Gateway's `create_payment_link` is invoked and its result recorded on the case.
- [ ] The case and its recorded outcome are visible in a minimal dashboard list view.
- [ ] End-to-end path is demoable: POST a synthetic payload → case appears in the dashboard with a recorded fake execution.
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
