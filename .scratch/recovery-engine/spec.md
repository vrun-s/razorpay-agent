Status: ready-for-agent

# Recovery Engine — spec

## Problem Statement

A Merchant selling through Razorpay loses Revenue at Risk in two well-understood, reactive moments: a payment fails at checkout, or a subscription exhausts Razorpay's own automatic retry ladder and is marked `halted`. Today, recovering that revenue is either fully manual (someone notices and follows up) or non-existent — nobody watches every failed payment or halted subscription and decides, case by case, whether it's worth a payment link, a discount, another retry, or nothing at all. A generic "chatbot that offers a coupon" isn't the answer either: not every case is worth the same intervention, incentive spend has to be bounded against a real budget shared across every case competing for it, and a merchant needs to trust *why* the system did what it did, not just that it did something.

## Solution

An AI-driven recovery engine that watches for `payment.failed` and `subscription.halted` events, treats each one as a Recovery Case that persists until resolved, and repeatedly reassesses each case's recovery probability and economics to decide the next Intervention — a further attempt, an escalation to a human, or a deliberate stop — executing through real Razorpay APIs (Payment Links, Resume Charge) and always validating the AI's proposal against merchant-defined Policy Engine constraints before anything touches money. Cases stream through one at a time, in arrival order, against a Recovery Budget with a deliberately-withheld Reserved Budget, exactly as it would in production — never a batch optimization with foresight the system doesn't actually have. Recovery probability comes from a per-cell Bayesian estimator that updates online as cases resolve, not an LLM guess; the LLM's job is fixed and bounded (diagnose the failure reason, narrate the reasoning for the audit trail, flag qualitatively escalation-worthy cases). A Synthetic Merchant Simulator, built independently of the estimator, generates the case volume needed to prove the system works and to measure Net Recovered Revenue and Incremental Recovery against baselines — with a small, separate slice of cases also run through real Razorpay to prove the integration mechanics are real, not simulated.

## User Stories

### Detection and case creation

1. As the recovery engine, I want to receive and verify a Razorpay `payment.failed` webhook (HMAC-SHA256 over the raw body), so that I only act on events that genuinely came from Razorpay.
2. As the recovery engine, I want to receive and verify a Razorpay `subscription.halted` webhook the same way, so that both workflows share one trusted ingestion path.
3. As the recovery engine, I want to deduplicate incoming webhooks by `x-razorpay-event-id`, so that Razorpay's non-ordered, non-exactly-once delivery never creates two Recovery Cases for one real event.
4. As the recovery engine, I want a synthetic `payment.failed` or `subscription.halted` payload (matching Razorpay's documented schema, signed with our own webhook secret) to be indistinguishable from a real one at the ingestion boundary, so that the exact same code path is exercised whether the source is the Synthetic Merchant Simulator or real Razorpay.
5. As the recovery engine, I want every accepted event to create exactly one new Recovery Case (or attach to an existing one if it re-fires for a case already open), so that a case is never duplicated or silently dropped.
6. As the recovery engine, I want every Recovery Case to record whether it originated from a real or simulated event, so that the estimator can exclude real-executed outcomes from its evidence stream per the simulator↔Razorpay execution boundary.

### Case lifecycle and reassessment

7. As the recovery engine, I want a new Recovery Case to immediately run its first Reassessment, so that a decision is made without waiting for an arbitrary first tick.
8. As the recovery engine, I want a Reassessment to trigger immediately when a real, outcome-relevant webhook arrives (e.g. the payment underlying a case succeeds), so that a resolved case closes the moment it's actually known, not on the next scheduled sweep.
9. As the recovery engine, I want a scheduled sweep to catch cases whose Response Window has elapsed with no outcome, so that a silent customer is itself treated as a signal, not an indefinite wait.
10. As the recovery engine, I want each Reassessment to consider Customer History and Case History together, so that the decision reflects both who the customer is and what's already been tried on this specific case.
11. As the recovery engine, I want repeated interventions on the same case to show a fatigue/diminishing-returns effect via Case History, so that the system doesn't propose the same discount five times in a row expecting the same lift.
12. As the recovery engine, I want a case to be explicitly stopped once further intervention is no longer economically justified, so that `NO_ACTION` (including "stop entirely") is a real, deliberate, auditable decision rather than the absence of one.
13. As the recovery engine, I want a stopped case's reasoning to be visible in the audit trail, so that "why did the AI give up here" always has a documented answer.
14. As the recovery engine, I want policy parameters (`max_payment_retries`, `max_halted_recovery_attempts`, `max_interventions_per_customer`) to function as hard sequence-length bounds on a case, so that a case cannot loop indefinitely even if the estimator keeps recommending another attempt.

### Decision engine

15. As the recovery engine, I want to compute a `customer_segment_proxy` deterministically from observable Customer History fields (order count, average order value, payment-reliability rate) via fixed thresholds, so that segmentation is reproducible and never an LLM judgment call.
16. As the recovery engine, I want recovery probability to come from a Beta-Bernoulli posterior per `(failure_reason × customer_segment_proxy × intervention)` cell, starting from a flat `Beta(2,2)` prior, so that the number is calibratable and defensible under scrutiny.
17. As the recovery engine, I want the posterior to update online (`α += 1` on success, `β += 1` on failure) only from the synthetic simulation stream, so that real-executed outcomes — which are a replay of a decision already counted, not independent evidence — never double-count.
18. As the recovery engine, I want an LLM to diagnose `failure_reason` from unstructured decline text or bank codes, so that cases with messy real-world inputs still map to a clean estimator cell.
19. As the recovery engine, I want an LLM to generate the natural-language justification attached to each Reassessment's decision, so that the audit trail reads as a reason, not just a number.
20. As the recovery engine, I want an LLM to flag a case as escalation-worthy when the signal is qualitative (e.g. an angry or confused customer response) even if the quantitative estimate wouldn't trigger escalation on its own, so that the system doesn't miss escalations a rules table would.
21. As the recovery engine, I never want the LLM to produce the recovery-probability number itself, so that the one number the whole economic case rests on always traces back to the Bayesian estimator, not a guess.
22. As the recovery engine, I want to expose an explicit uncertainty measure (e.g. credible interval width) alongside the posterior's point estimate, so that the allocator can treat a sparse, shaky cell as riskier without a separate exploration algorithm.

### Policy enforcement

23. As a Merchant, I want to define a maximum discount percentage, so that the AI can never propose an incentive beyond what I've authorized.
24. As a Merchant, I want to define a maximum incentive amount, `max_payment_retries`, `max_halted_recovery_attempts`, and `max_interventions_per_customer`, so that I bound both spend and contact frequency (including for compliance reasons — I cannot dunning-spam a customer).
25. As a Merchant, I want to define escalation thresholds, so that cases above a certain value or risk are routed to a human rather than resolved autonomously.
26. As the Policy Engine, I want to validate every AI-proposed Intervention against these constraints before anything executes, so that the AI proposes but never acts on money directly.
27. As the Policy Engine, I want to reject a proposed Intervention that violates a constraint and record the rejection (which constraint, what was proposed instead of executed), so that a policy rejection is visible in the audit trail, not silently substituted.
28. As the recovery engine, I want a workflow to declare which subset of the shared `Intervention` type is valid for its own cases, so that (for example) `Payment Retry` never appears as an option for a halted-subscription case, and vice-versa for `Resume Charge`.

### Budget and streaming allocation

29. As the streaming allocator, I want to process cases one at a time in arrival order, so that no decision requires foresight into cases that haven't arrived yet.
30. As the streaming allocator, I want to withhold a Reserved Budget against the expectation that better-value cases may still arrive, so that the Recovery Budget isn't exhausted on a mediocre early case.
31. As the streaming allocator, I want to visibly decline a mediocre case at one point in a demo run and later spend on a better one, so that the reserve mechanism's value is observable, not just theoretical.
32. As the recovery engine, I want to compute an Offline-Optimal Allocation retrospectively over a fully-observed case set, so that "the online agent captured N% of offline-optimal" has a real number behind it — reported only as an evaluation baseline, never as what the agent itself decided live.

### Execution

33. As the Executor, I want one gateway abstraction (`create_payment_link`, `resume_charge`, webhook ingestion) that both the Synthetic Merchant Simulator and real Razorpay drive from the outside, so that the recovery engine's core logic never knows or cares which one it's talking to.
34. As the Executor, I want to create a real Razorpay Payment Link for a failed-payment case chosen for a Payment Retry-class intervention, so that the customer receives a real, payable link.
35. As the Executor, I want to call Resume Charge for a halted-subscription case chosen for revival, so that a fresh charge attempt happens only after Razorpay's own three automatic retries are already exhausted, never before.
36. As the Executor, I want every execution to be logged with the Razorpay order/payment/subscription ID it touched, so that a case's audit trail can be cross-referenced against Razorpay's own dashboard.
37. As the recovery engine, I want the real-Razorpay execution slice to stay within Razorpay's documented test-mode Payment Links cap (30/business), so that the integration-proof slice never gets rate-limited mid-demo.

### Escalation

38. As a human reviewer, I want an Escalated case to appear in a dashboard queue with its full Case History and the AI's reasoning attached, so that I have everything needed to make a decision without digging through raw logs.
39. As a human reviewer, I want to either override an escalated case with my own chosen Intervention or manually resolve/close it, so that escalation is a real decision point, not a dead end.
40. As the recovery engine, I want a human's override or resolution to be written back into Case History exactly like any other intervention outcome, so that there is one audit trail, not a side channel that falls out of sync with the rest of the case's story.

### Measurement and evaluation

41. As a judge/evaluator, I want Net Recovered Revenue (gross recovered minus incentive cost) reported as the optimization target, so that a "recovery" that cost more than it returned is never counted as a win.
42. As a judge/evaluator, I want Incremental Recovery measured against a no-intervention baseline and a fixed-rule baseline (blanket 5% discount), so that the AI's contribution is isolated from recovery that would have happened anyway.
43. As a judge/evaluator, I want the headline comparison run as a paired counterfactual replay — the same case stream, shared RNG seed, across no-intervention, fixed-rule, AI treatment, and offline-optimal — so that the comparison is apples-to-apples, not four separate uncontrolled runs.
44. As a judge/evaluator, I want the AI-vs-baseline gap reported with a bootstrap confidence interval, not a bare point estimate, so that the result isn't overstated as more certain than the sample supports.
45. As a judge/evaluator, I want a misspecification stress test (persona mix, response-curve elasticities, fatigue decay rate each perturbed ±20%) rerun against the full paired evaluation, with the AI-vs-baseline lift required to survive at least 2 of 3 perturbations, so that the headline number isn't fragile to the simulator's exact assumptions.
46. As a judge/evaluator, I want a calibration curve (predicted vs. actual recovery probability), so that I can check the estimator's numbers mean what they claim to mean, not just that they correlate with outcomes.
47. As the evaluation harness, I want 300 dev / 150 validation / 200 held-out synthetic cases, with the held-out set never tuned on, so that the reported numbers aren't quietly overfit to the test set.
48. As the evaluation harness, I want the estimator's priors and feature design built without visibility into the Synthetic Merchant Simulator's actual response-curve parameters, so that "the AI learned the right thing" isn't secretly "the AI was told the right thing."

### Demo and observability

49. As a judge watching a live demo, I want to see one case's full timeline — detected → decision + reasoning → policy check (naming the constraint that bound it) → execution → webhook → reassessment → stop — with timestamps, so that the whole loop is visible end to end in one place.
50. As a judge watching a live demo, I want to see the Reserved Budget as a moving quantity over the course of a run, so that the reserve mechanism reads as a real, active decision rather than a line in an ADR.
51. As a judge watching a live demo, I want to see at least one `NO_ACTION` case that recovered anyway, so that "the AI knows when not to spend" is demonstrated, not just claimed.
52. As a judge watching a live demo, I want to see at least one policy rejection and one escalation with a human override, so that both halves of the "AI proposes, human/policy governs" story are shown, not just the happy path.
53. As a Merchant using the dashboard, I want an aggregate view of Net Recovered Revenue vs. both baselines with a confidence interval and % of offline-optimal, so that I can judge the system's value at a glance.

## Implementation Decisions

- **Modules**: Webhook Ingestion (verification + dedupe, shared by both workflows), Recovery Case store (persistent state machine: created → active reassessment loop → resolved as recovered / stopped / escalated), Decision Engine (Beta-Bernoulli estimator + bounded LLM role per [[0006-decision-engine-estimator]]), Policy Engine, Streaming Allocator (reserve budget per [[0003-streaming-allocation]]), Executor / Razorpay Gateway (the one seam — `create_payment_link`, `resume_charge`, webhook parsing), Reassessment Scheduler (webhook-triggered + scheduled sweep per [[0005-hybrid-reassessment-trigger]]), Synthetic Merchant Simulator (built and versioned independently of the estimator per [[0007-evaluation-integrity]]), Evaluation Harness (paired counterfactual replay, bootstrap CI, misspecification stress test), and a React dashboard (case queue, live timeline, budget-reserve visualization, escalation queue with override, aggregate measurement view).
- **The one seam**: everything above the Executor/Razorpay Gateway line is testable with zero real Razorpay calls. The gateway interface is implemented twice — once against real Razorpay (for the small integration-proof slice), once driven by the Synthetic Merchant Simulator (for volume and evaluation) — and the recovery engine's core code never branches on which one it's talking to.
- **Two workflows share one engine** per [[0002-pluggable-workflow-abstraction]]: failed-payment recovery and halted-subscription recovery each supply their own detector (which webhook type creates a case) and their own valid `Intervention` subset (`Payment Retry` only for failed-payment; `Resume Charge` only for halted-subscription), reusing the same Decision Engine, Policy Engine, Streaming Allocator, and measurement layer.
- **Escalation**: a case state (`Escalated`), surfaced in a dashboard queue with full Case History and the LLM's reasoning attached. A human either overrides with their own Intervention choice or manually resolves/closes the case; either action writes back into Case History like any other intervention outcome — one audit trail, not a side channel.
- **Source tagging**: every Case History entry records whether its underlying event was `real` or `simulated`, per [[0006-decision-engine-estimator]] — required for the estimator's exclusion rule, and useful in the dashboard to distinguish the integration-proof slice from the evaluation volume.
- **Budget/allocation**: implements the reserve-withholding policy from [[0003-streaming-allocation]]; Offline-Optimal Allocation is computed only retrospectively, over a fully-observed case set, purely as an evaluation baseline.
- **Real-Razorpay slice**: a small, hand-picked ~20–25 case slice runs through real Razorpay test mode purely to prove the integration mechanics (payment links actually get created, resume-charge actually fires, webhooks actually arrive and verify) — bounded by Razorpay's 30-Payment-Link-per-business test-mode cap — kept entirely separate from the 300/150/200 synthetic evaluation split, which has no relationship to that cap.
- **Compliance-adjacent policy**: `max_interventions_per_customer` doubles as the enforcement point for not dunning-spamming a customer (a real-world constraint, not just politeness) — no separate compliance module is needed beyond this existing Policy Engine parameter.

## Testing Decisions

- **What makes a good test here**: assert on behavior observable at the one seam (what the Executor was asked to do, what case state resulted, what the Policy Engine allowed/rejected and why) — never on internal estimator implementation details like exact posterior storage layout.
- **Synthetic payloads as prior art**: the halted-subscription empirical investigation this session already established the pattern — hand-construct a JSON payload matching Razorpay's documented webhook schema, sign it with the webhook secret, and feed it through the real ingestion code path. Every workflow's webhook handling should be tested the same way (`payment.failed` needs its own synthetic payload built the same way).
- **Modules to test**: Webhook Ingestion (signature verification, dedupe, malformed-payload rejection), Policy Engine (every constraint has at least one test that proves it actually blocks a violating proposal), Decision Engine (posterior update arithmetic, `customer_segment_proxy` threshold logic, uncertainty measure exposed correctly), Streaming Allocator (reserve-withholding behavior under a small deterministic case sequence), Case lifecycle (fatigue/diminishing-returns effect, sequence-length bounds, stop/escalate transitions), Executor (against a fake Razorpay gateway — correct calls made with policy-bounded arguments, never a raw unbounded value).
- **Evaluation is tested separately from unit/integration tests**: the paired counterfactual replay, bootstrap CI, and misspecification stress test are themselves part of what ships (per [[0007-evaluation-integrity]]) — treat the evaluation harness as a module with its own tests (e.g. a fixed synthetic seed reproduces the same reported numbers on rerun), not as a one-off script.

## Out of Scope

- Checkout abandonment (deferred per [[0001-defer-checkout-abandonment]] — no server-visible signal without gated Magic Checkout).
- Receivables/invoice chasing — plausible future workflow enabled by the pluggable abstraction, not built now.
- Predictive (pre-failure) risk detection — both shipping workflows are reactive/event-triggered only.
- Conversational/chatbot recovery mechanism — the original brainstormed idea; superseded by Payment Links and Resume Charge as the actual recovery actions.
- Adaptive learning beyond the fixed Beta-Bernoulli online update (e.g. no separate exploration algorithm like Thompson sampling — uncertainty is consumed by the allocator instead, per [[0006-decision-engine-estimator]]).
- Any workflow or scenario beyond the two committed ones, if time runs short — per the project's own pre-committed cut order: halted-subscription workflow → adaptive learning → chaos beyond 3 scenarios → conversational recovery, cut in that order if the build falls behind.
- A dedicated compliance ADR or module beyond the existing `max_interventions_per_customer` policy parameter.

## Further Notes

- This spec covers the full recovery-engine MVP as one unit rather than being split further, since the two workflows deliberately share one engine and evaluation design — ticket-splitting (`/to-tickets`) is where this gets broken into buildable, ordered pieces, not here.
- The demo script (test2108.md §13) should be written early, not on the last day — it directly names what the dashboard and case-timeline UI need to make visible (reserve budget moving, a `NO_ACTION` case that still recovered, one policy rejection, one human-overridden escalation, the aggregate comparison, the calibration curve). Building toward that list is a reasonable proxy for "is the MVP actually demonstrable," not just "does it pass tests."
- `docs/razorpay_track3_initial_context.md` remains historical background; `CONTEXT.md` + `docs/adr/0001`–`0007` + this spec are the canonical source of truth going forward.
