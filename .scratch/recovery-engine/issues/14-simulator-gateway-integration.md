# 14: Simulator integration into the gateway seam

**What to build:** Wire ticket 02's already-frozen generator into ticket 13's simulator-backed fake Gateway implementation, so synthetic cases flow through the real ingestion/execution code paths at volume.

**Blocked by:** 02, 13

**Status:** ready-for-agent

- [ ] The frozen generator from ticket 02 drives the simulator-backed fake Gateway: outcomes are drawn from its response curves given the case's hidden ground truth.
- [ ] The Decision Engine and rest of the system see only synthetic events/webhooks shaped identically to real Razorpay payloads — no code path branches on "this is simulated" except the source tag.
- [ ] Every case generated this way is recorded with a `simulated` source tag in Case History, per ticket 07's exclusion rule.
- [ ] Test: driving N synthetic cases through the full pipeline produces outcome rates that plausibly match the generator's known response curves (statistical sanity check, not exact equality).
- [ ] All acceptance criteria verified and changes committed to git before starting the next ticket.
