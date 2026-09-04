# Razorpay Revenue Recovery

An AI agent that manages revenue-recovery cases over time rather than making one-shot recommendations: it continuously reassesses the probability and economics of recovery, chooses the next merchant-approved intervention, observes the outcome, escalates when appropriate, and stops when further intervention is no longer justified — executing through Razorpay and measuring the incremental net revenue recovered.

## Language

**Merchant**:
The business selling through Razorpay whose revenue is at risk and who defines recovery policy.
_Avoid_: Seller, business

**Revenue at Risk**:
Money already expected/in motion that is at risk of not converting — a cart, a payment, a subscription charge, or an invoice.
_Avoid_: Lost revenue (that implies it's already gone; this is still recoverable)

**Recovery Case**:
A persistent instance of revenue at risk, tracked from detection through final resolution, identified by a `recovery_id`. A case is not resolved by a single intervention — it lives across multiple reassessments until it's recovered or explicitly stopped ([[0004-cases-as-sequences]]).
_Avoid_: Ticket, event (an event is what *triggers* a case, or what happens *within* one; the case is the persistent unit that outlives any single event)

**Reassessment**:
The agent re-evaluating a case's recovery probability and economics to choose what happens next — a further intervention, escalation, or stopping. Triggered either by a real outcome (a relevant Razorpay webhook) or by a Response Window elapsing with no outcome ([[0005-hybrid-reassessment-trigger]]) — silence is itself a trigger, not just an absence of one.

**Response Window**:
The time period during which a case's current intervention is expected to produce an outcome before its absence becomes a reassessment trigger in its own right.

**Intervention**:
The recovery action chosen for a case, drawn from one shared `Intervention` type used by every workflow (required so the engine in [[0002-pluggable-workflow-abstraction]] stays generic) — but each workflow declares which subset of it is valid for its own cases, not all of them. `NO_ACTION` is a deliberate, valid intervention in every workflow, not the absence of one — recovery attempts have a cost, and sometimes the right call is to spend nothing.
_Avoid_: Action (reserve "action" for the executor's side of the loop, after policy validation)

**Payment Retry** (failed-payment recovery only):
Re-attempting the original charge on the same payment method, for a case where no successful attempt has happened yet.
_Avoid_: Using this term for the subscription workflow's revival action — see Resume Charge.

**Resume Charge** (halted-subscription recovery only):
Triggering a fresh charge attempt on a subscription after it has reached `halted`, i.e. after Razorpay's own three automatic retries are already exhausted. This is a materially different operation from Payment Retry even though both are colloquially "trying to charge the customer again" — Razorpay already owns the retry decision for the first three attempts, so this only exists past that point.
_Avoid_: Payment Retry (that term is reserved for the failed-payment workflow, to avoid the same name silently meaning two different operations)

**Policy Engine**:
The deterministic component that validates an AI-proposed intervention against merchant-defined constraints (max discount, recovery budget, retry ceiling, escalation thresholds) before anything executes. The AI proposes; it never acts on money directly.
_Avoid_: Guardrails (fine informally; Policy Engine is the canonical component name)

**Incentive**:
A merchant-funded sweetener — a discount or account credit — bundled with a Payment Retry or Resume Charge to raise the odds the customer completes. Its cost (`incentive_amount`, paise) is what the Policy Engine and Streaming Allocator gate, and it is drawn against the Recovery Budget. An intervention carrying no incentive is still a valid, zero-cost attempt; `NO_ACTION` never carries one ([[0014-flat-incentive-response-learnable-deferred]]).
_Avoid_: Discount (one form an incentive can take; "incentive" is the budgeted concept)

**Recovery Budget**:
The merchant-defined ceiling on total Incentive spend across a population of cases. Cases are allocated against it as a stream, not a known-upfront batch ([[0003-streaming-allocation]]) — the system maximizes net recovery, not case count, without foresight into cases that haven't arrived yet.

**Reserved Budget**:
The portion of the Recovery Budget the streaming allocator deliberately withholds at any given moment, against the expectation that better-value cases may still arrive. Distinct from spent budget (already committed to executed interventions) and available budget (spendable right now without touching the reserve). Applied on every live and demo path; the evaluation harness is the one exception — it runs with the reserve switched off because its single-cell estimator gives nothing to ration on ([[0016-evaluation-harness-runs-without-reserve]]).

**Offline-Optimal Allocation**:
A retrospective, batch-computed allocation over a case set already fully observed, used only as an evaluation baseline for how close the live streaming allocator came to the best possible outcome — never presented as a decision the agent itself made, since the agent never had that foresight. Its only advantage over the live allocator is foresight — it knows, per case, which interventions would have recovered it and how much the case is worth. It is otherwise bound by the *same* limits as the online arms: the same Recovery Budget, the same per-case retry ceiling, the same per-workflow set of valid interventions, and it pays the same Incentive cost for every intervention it commits. It does not withhold a Reserved Budget — it has no unknown future arrivals to hedge against. Those constraints are what keep "% of Offline-Optimal captured" a measure of allocation quality alone, rather than of unequal budgets or attempt counts ([[0013-evaluation-metric-baselines-contract]]).
_Avoid_: Treating it as a true optimum — it is a deliberately constrained reference ceiling, computed as a heuristic, not the unconstrained best outcome imaginable.
_Implementation gap (2026-09)_: `app/evaluation.py::run_offline_optimal_arm` does not yet enforce the budget and incentive-cost constraints described above — it has no Policy Engine or Streaming Allocator in the loop, charges **zero** Incentive cost, and ignores the Recovery Budget, giving every candidate a full guaranteed attempt budget. So its NRR is gross-recovered with no incentive deduction, and "% of Offline-Optimal captured" is currently a loose reference rather than the constrained ceiling. A budget-constrained knapsack is deferred; see `docs/evaluation-findings-2026-09.md`.

**Net Recovered Revenue**:
Gross revenue recovered minus incentive cost, for a case or a batch. This — not raw recovery rate — is the system's optimization target.
_Avoid_: Revenue recovered (ambiguous between gross and net; always qualify which one)

**Incremental Recovery**:
The difference between the AI treatment's recovery outcome and a baseline's (no-intervention, or a fixed simple rule) on the same population. This is what proves the AI caused the recovery, not just that recovery happened to correlate with it.

**Synthetic Merchant Simulator**:
The controlled environment that generates revenue-loss cases along with a known ground-truth outcome distribution per possible intervention — known to the simulator, hidden from the decision engine — used to score how close the engine's choices come to optimal.

**Customer Segment**:
The underlying persona (e.g. loyal, bargain hunter, new, unreliable payer) the Synthetic Merchant Simulator uses to generate a customer's internally-consistent behavior. Simulator ground truth only — never exposed to the decision engine directly, for the same reason per-case outcome odds aren't: the agent has to infer customer type from Customer History, not be handed the answer.

**Customer Segment Proxy**:
A small set of discrete buckets the decision engine computes deterministically from observable Customer History fields (order count, average order value, payment-reliability rate) via fixed thresholds. One axis of the recovery-probability estimator's `(failure_reason × customer_segment_proxy × intervention)` cells.
_Avoid_: Customer Segment (that's the simulator's hidden ground-truth persona; the proxy is a deliberately weaker signal computed from what the engine can actually observe, not a stand-in quietly treated as the real thing)

**Customer History**:
A customer's own observable record across everything they've done with the merchant — order count, average order value, payment reliability, and responses to past Recovery Cases — independent of any single case. Feeds a Reassessment as context alongside Case History; the two are complementary, not interchangeable.

**Case History**:
The record of what's happened within one specific Recovery Case — which interventions were tried, in what order, with what outcomes. Drives the state-dependent (fatigue/diminishing-returns) effect a Reassessment accounts for.
