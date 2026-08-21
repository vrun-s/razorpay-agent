# Razorpay Buildathon — Track 3 Project Context / Handoff Summary

## Status update — grilling session, 2026-08-21

This document is the original brainstorm/handoff summary. A `/grill-with-docs` session has since resolved its open questions into concrete decisions. **`CONTEXT.md` (repo root) and `docs/adr/0001`–`0005` are now the canonical source of truth** — read those first. This doc stays as historical record of the original idea space; several of its sections below are superseded by what follows.

Key resolutions:
- **Checkout abandonment is deferred**, not built (`docs/adr/0001-defer-checkout-abandonment.md`) — standard Razorpay Checkout gives no server-visible signal before a payment attempt exists; a real signal exists only via the gated Magic Checkout product, test-mode support unconfirmed. Revisit later.
- **Shipping workflows**: failed-payment recovery (via Payment Links) + halted-subscription recovery — chosen over pure subscription-retry framing because Razorpay auto-retries a subscription non-interruptibly for its first ~4 days, so agent decision authority there only starts at `halted`.
- **The engine is pluggable from day one** (`0002-pluggable-workflow-abstraction.md`), so checkout abandonment and receivables/invoice-chasing (a real, separate Invoices API — confirmed during grilling) can be added later without a rewrite.
- **Allocation is streaming/online with a reserve budget**, not the batch optimization the "Strongest demo concept" section below assumes (`0003-streaming-allocation.md`) — an offline-optimal calculation still runs retrospectively as an evaluation baseline, not as how the agent itself operates.
- **Cases are multi-step sequences with continuous reassessment**, not single-shot decisions (`0004-cases-as-sequences.md`), triggered by both real webhooks and response-window timeouts (`0005-hybrid-reassessment-trigger.md`) — silence is itself a signal, needed for the "promise-to-pay tracker" behavior this doc names below.
- **Ground truth is state-dependent across a case's own history** (fatigue/diminishing returns from repeated contact), and **customer identity/persona is simulator-only ground truth** — never exposed directly to the decision engine, which must infer customer type from observable Customer History, the same discipline already applied to per-case outcome odds.
- **Predictive (pre-failure) risk detection is deprioritized**, contrary to this doc's Tier S #1 below — both shipping workflows are reactive/event-triggered (`payment.failed`, `subscription.halted`); predictive scoring mainly belonged to the now-deferred checkout-abandonment workflow.
- **Razorpay facts confirmed via research** (not in this doc originally): subscriptions auto-retry 3 times over ~4 days before halting, non-interruptible by an integrator; Payment Links are capped at 30/business in test mode (Subscriptions have no documented equivalent cap); webhook delivery isn't ordered or exactly-once (dedupe by `x-razorpay-event-id`, verify HMAC-SHA256 over the raw body); test-mode API keys need no KYC; a test-mode card token is valid only 3 days, relevant to subscription debit timing.

Project facts as of this session: solo build, full-time (5–15 hrs/day) across the 15-day window, FastAPI (Python) + React, no Razorpay test-mode account set up yet — first practical to-do regardless of what else happens next.

## User's goal

I am a final-year B.Tech IT student preparing for the **Razorpay Buildathon**. I have approximately **15 days** to build the project and have freedom to use AI coding agents / Claude Code / other AI tools.

My goal is **not merely to submit something that technically fits the track**. I want to build something strong enough to:

1. Stand out among other AI-assisted teams.
2. Demonstrate serious engineering ability.
3. Potentially impress Razorpay engineers enough to help with an **internship opportunity**.
4. Be technically ambitious/risky rather than another generic "AI chatbot + dashboard" project.

I explicitly asked the assistant to **be brutally honest, not glaze/top-glaze my ideas**, and to challenge weak assumptions.

---

# Buildathon tracks

## Track 01 — AI Growth & Agentic Commerce

Grow the merchant's revenue, and make them sellable to AI buyers.

Examples:
- Conversational in-app checkout
- Agent-readable catalog
- Upsell/cross-sell agent
- Campaign orchestrator

Bar:
> Every money action explainable, bounded and gated. Show audit trail and one failure handled gracefully.

## Track 02 — AI Risk Manager

Stop the merchant losing money to fraud, returns and chargebacks.

Examples:
- Chargeback evidence responder
- Return-risk scorer
- Fraud-spike detector
- Abuse-ring sentinel

Defense-only.

## Track 03 — AI Revenue Recovery — CHOSEN TRACK

Find revenue that’s slipping away and win it back.

Build an agent that:
1. Detects revenue at risk.
2. Determines the right intervention.
3. Executes a bounded recovery workflow.
4. Shows measured money recovered across a batch.
5. Has compliant escalation, stopping rules and an audit trail.

Examples:
- Payment degradation → root cause → recovery action
- Checkout drop-off recovery
- Failed-subscription recovery
- B2B receivables chaser
- Mandate retry sequencer
- Hinglish voice recovery
- Promise-to-pay tracker

---

# Merchant definition

A merchant is the business/person selling something and receiving payments through Razorpay.

Mental model:

Merchant / Seller → Razorpay → Customer / Buyer

---

# Initial idea

User proposed:

> If a user wants to abandon their cart, bring up a chatbot that asks why. If the reason is valid, e.g. "found better prices elsewhere", the agent tries to retain them using incentives such as a 1–5% discount coupon. If the agent actually retains them and they make a successful purchase, this should count as revenue recovery.

Assessment:
- This does fit Track 3.
- But chatbot + coupon alone is weak/generic.
- It was initially assessed around 6/10.
- The user clarified that the chatbot is **not** the whole submission.

---

# Actual intended project

The real concept is:

> **An AI Revenue Recovery Decision Engine that detects potential revenue loss, determines what recovery action should be taken according to merchant-defined rules/policies, executes the action, verifies whether money was recovered, and learns/measures the outcome.**

The chatbot is only **one possible recovery mechanism**.

Core loop:

DETECT → CONTEXT → AI DECISION → MERCHANT POLICY → ACTION → VERIFY → MEASURE → LEARN

---

# Why it fits Track 3

### Detect revenue at risk
Potential sources:
- checkout abandonment
- payment failure
- subscription payment failure
- overdue receivables
- other payment/revenue leakage events

### Determine right intervention
Potential actions:
- no action
- reminder
- discount
- free shipping
- conversational assistance
- payment retry
- payment link
- escalation

### Execute bounded workflow
Merchant defines:
- max discount
- max incentive amount
- max retries
- recovery budget
- approval thresholds
- max interventions/customer
- stopping conditions

### Measure money recovered
Track:
- revenue at risk
- gross recovered
- incentive cost
- net recovered revenue
- recovery rate
- incremental recovery vs baseline

### Audit trail
Every recovery should have a unique recovery ID and full event trail.

---

# Critical architecture principle

Do **not** let an LLM directly control money.

Use:

AI proposes → Policy engine validates → Executor acts

Example:

AI: "Recommend 3% discount"
↓
Policy Engine: "Maximum allowed = 5%, customer eligible"
↓
Approved
↓
Action Executor
↓
Razorpay API

This gives bounded autonomy, explainability, safety and auditability.

---

# Proposed core architecture

RAZORPAY / MERCHANT EVENTS
↓
Revenue Risk Detection Engine
↓
Revenue at Risk
↓
Context Builder
↓
AI Decision Engine
↓
Policy Engine
↓
Action Executor
↓
Razorpay APIs
↓
Webhooks
↓
Verification
↓
Revenue recovered?
↓
Attribution / Audit
↓
Learning

---

# Candidate workflows

## Workflow 1 — Checkout abandonment

Customer enters checkout
→ abandonment / high-risk event
→ determine reason/context
→ AI chooses intervention
→ policy validation
→ coupon / free shipping / assistance / no-op
→ customer returns
→ Razorpay checkout
→ payment success
→ revenue recovered

Important:
Not every abandonment should be solved with a discount.

---

## Workflow 2 — Failed payment recovery

Payment attempted
→ FAILED
→ diagnose failure
→ AI determines next action
→ retry / notify / alternate payment route / stop
→ Razorpay action
→ webhook
→ success?
→ revenue recovered

Failure types:
- transient/network
- insufficient funds
- expired card
- bank decline
- unknown

Need:
- idempotency
- duplicate webhook handling
- retry ceilings

---

## Workflow 3 — Subscription payment recovery

Subscription ₹999/month
→ recurring payment fails
→ pending state
→ AI diagnoses
→ recovery sequence
→ retry / notify / payment link
→ verify
→ subscription recovered

This is a strong agentic workflow because the agent must decide what to do next and when.

---

# Research-backed revenue-loss categories discussed

Important categories:

1. **Checkout abandonment**
   - Baymard research indicates average cart abandonment is around 70%.
   - Common reasons include extra costs, slow delivery, lack of trust, forced account creation, complicated checkout, site errors, returns concerns, unclear total cost, card decline and insufficient payment methods.
   - Important: not all abandonment is genuinely recoverable.

2. **Failed payments**
   - Very relevant to Razorpay.
   - Payment companies build revenue-recovery systems around failed payments and intelligent retries.

3. **Subscription payment failures / involuntary churn**
   - Customer did not intentionally cancel but recurring payment fails.
   - Strong Track 3 opportunity.

4. **Overdue invoices / receivables**
   - Explicit Track 3 example.
   - AI can decide who to chase, when, how strongly, and when to escalate.

5. **Bad retry strategy**
   - Question isn't only "did payment fail?"
   - It is "when should we retry, should we retry, and when should we stop?"

6. **Returns/refunds**
   - Important but overlaps Track 2.

7. **Fraud/chargebacks**
   - Important but primarily Track 2.

8. **Upsell/cross-sell**
   - More Track 1 than Track 3.

---

# Track distinction

## Track 1
Potential revenue wasn't captured / how do we make customer spend more?
- upsell
- cross-sell
- recommendations
- AI shopping
- campaigns

## Track 3
Revenue was already expected/in motion and then became at risk.
- checkout abandonment
- failed payment
- failed subscription
- overdue invoice
- payment retry
- promise-to-pay

## Track 2
Money was lost because of risky behavior.
- fraud
- chargebacks
- returns
- abuse

---

# Major differentiator: Recovery Strategy Optimizer

Instead of:

Revenue at risk → give 3% coupon

Build:

Revenue at risk
→ customer/cart/payment context
→ Recovery Strategy Optimizer
→ evaluate possible actions
→ merchant constraints
→ choose action with best expected NET recovery

Possible actions:

NO_ACTION
REMINDER
FREE_SHIPPING
1% DISCOUNT
2% DISCOUNT
3% DISCOUNT
5% DISCOUNT
PRODUCT_ASSISTANCE
PAYMENT_RETRY
PAYMENT_LINK
HUMAN_ESCALATION

Objective:

> **Maximize incremental net revenue subject to merchant constraints.**

Not:
> maximize recovered orders.

---

# "Do nothing" is a valid action

This is important.

Intervention itself has a cost.

Example:
- customer likely to purchase anyway
- giving a ₹500 coupon is wasteful

Therefore the agent should be willing to say:

> **NO ACTION**

This is part of the differentiated thesis.

---

# Recovery budget allocation

Merchant can specify:

> "You have ₹50,000 recovery/incentive budget."

Agent receives 1,000 cases and decides who gets intervention.

Example:

Customer A:
₹20K at risk
Expected net recovery ₹6K
→ intervene

Customer B:
₹2K at risk
Expected net recovery ₹50
→ don't intervene

Customer C:
₹15K at risk
Expected net recovery ₹4K
→ intervene

This creates a real allocation/optimization problem.

---

# Predictive recovery

Very strong Track 3 fit because the track explicitly says:

> "detects revenue at risk"

Instead of waiting for:
> payment failed

predict:
> "this transaction/customer/order has high probability of becoming lost revenue."

Potential signals:
- checkout delay
- prior payment failures
- high cart value
- shipping cost
- previous abandonment
- customer history
- payment method
- session behavior

Prediction alone is insufficient. It must feed into action/recovery.

---

# Adaptive recovery

Closed loop:

DETECT
↓
DECIDE
↓
ACT
↓
OUTCOME
↓
LEARN
↓
IMPROVE

Example:
The system learns that for a segment, free shipping converts better than a 3% discount.

Important warning:
Do not fake learning with arbitrary synthetic labels.

---

# Multi-agent recovery

Possible architecture:

Discount Strategist
Payment Strategist
Retention Strategist
Conservative Strategist
↓
Recovery Orchestrator
↓
Economic evaluation
↓
Policy validation
↓
Action

Important brutal evaluation:

**Multi-agent is not inherently valuable.**

If it's just 5 LLMs arguing over coupons, it is unnecessary complexity.

Multi-agent is useful only if agents represent genuinely different recovery strategies.

A strategy evaluator/simulator may be better.

---

# Recovery attribution

User proposed:
> Give coupons an ID tied to the agent so we can prove the agent caused the recovery.

Assessment:
Good engineering, but not sufficient causal proof.

Use a recovery ID:

recovery_id
cart_id
customer_id
intervention
discount
coupon_code
Razorpay order ID
payment ID
final outcome

Full trace:

Revenue Risk
↓
Cart
↓
Reason
↓
AI Decision
↓
Policy Check
↓
Intervention
↓
Coupon/payment link
↓
Razorpay Order
↓
Payment
↓
Outcome

This proves linkage to the recovery workflow, but does not by itself prove causality.

Need a control group.

---

# Experimental design

At minimum compare:

### Baseline 1
No intervention.

### Baseline 2
Fixed/simple rule, e.g. blanket 5% discount.

### Treatment
AI decision engine.

Potentially:
### Adaptive AI
AI learns from outcomes.

Use same underlying population for comparison.

Example:

Control recovery = 8.2%
AI recovery = 14.7%
Incremental recovery = +6.5 percentage points

---

# Metrics

Measure:

### Revenue at risk
How much money is potentially lost.

### Gross revenue recovered
Money recovered after intervention.

### Incentive cost
Discount/free-shipping cost.

### Net recovered revenue

Gross recovered revenue - incentive cost

### Recovery rate

Recovered cases / eligible cases

### Incremental recovery

AI treatment conversion - control conversion

### Intervention rate
How often the system acts.

### Waste / unnecessary intervention
How often incentive is given to a customer who would have purchased anyway.

### Policy violations
Target = 0.

### Retry count
Must respect configured limits.

---

# Synthetic merchant simulator

Do not merely invent final revenue numbers.

Build a controlled merchant simulator.

Merchant:
- products
- customers
- orders
- carts
- payments
- subscriptions
- invoices
- merchant policies
- recovery budget

The simulator should generate events that behave like real revenue-loss scenarios.

---

# Synthetic customer personas

Examples:

### Loyal customer
- many purchases
- high AOV
- low price sensitivity
- high payment reliability

### Bargain hunter
- high price sensitivity
- high coupon usage

### New customer
- no history

### Unreliable payer
- high historical payment failure rate

This provides context for the AI.

---

# Revenue-loss simulation scenarios

## Checkout abandonment
Customer
→ add product
→ checkout
→ abandon

Possible reasons:
- price
- shipping
- uncertainty
- just browsing
- payment issue
- technical issue

## Payment failure
Order
→ payment attempt
→ failed

Failure types:
- transient
- insufficient funds
- expired card
- network
- bank decline
- unknown

## Subscription failure
Month 1 ✓
Month 2 ✓
Month 3 ✓
Month 4 ❌

Agent determines recovery sequence.

---

# Ground truth and counterfactual evaluation

The simulator should know underlying behavior that the agent does NOT know.

Example:

Customer C123
Cart = ₹5,000

Simulator truth:
- no intervention → 8% purchase
- 1% discount → 15%
- 2% discount → 27%
- 3% discount → 28%
- 5% discount → 29%

Agent sees only context.

This enables evaluation:
- Did agent choose a good action?
- How close was it to optimal?
- Did it waste incentive budget?

Do not claim this is real-world causal data if it is simulated.

---

# Dataset split

Suggested:

### Development
5,000 cases.

### Validation
2,000 cases.

### Final held-out test
3,000 cases.

Do not tune the final test.

---

# Razorpay test-mode integration

Use both:

## Synthetic environment
Controls:
- customer behavior
- revenue events
- outcomes
- ground truth

## Razorpay test mode
Handles:
- actual API integration
- orders
- payments
- subscriptions
- webhooks
- payment state changes

Architecture:

Synthetic event
→ AI engine
→ Razorpay test API
→ actual test event
→ webhook
→ measurement

Be honest:
> Evaluation uses a synthetic controlled environment calibrated to observed behavior, while payment/action execution is demonstrated using Razorpay test-mode infrastructure.

Never claim synthetic revenue as real merchant revenue.

---

# Razorpay-specific design

To make the project feel like a Razorpay project rather than a generic AI project, Razorpay must be the actual payment infrastructure, not just the payment button.

Use Razorpay as:

### Event source
Payment/order/subscription webhooks.

### Execution layer
Payments, payment links, subscription recovery actions where supported.

### Verification source
Razorpay webhook/payment state confirms recovery.

### Data model
Merchant, Customer, Order, Payment, Subscription, Payment Link, Webhook Event, Recovery Case.

The project becomes:

Razorpay event
→ Revenue Risk Event
→ AI decision
→ Razorpay action
→ Razorpay webhook
→ measured recovery

---

# Razorpay-native event architecture

Potential events:

payment.failed
payment.authorized
payment.captured
order.paid
subscription.pending
subscription.halted
payment_link.paid

These should feed a common event-ingestion/revenue-risk layer.

---

# Strong Razorpay workflow: subscription recovery

Potential demo:

Razorpay Subscription
₹999/month
↓
Recurring charge fails
↓
subscription.pending
↓
Your AI agent
↓
Analyze customer history/failure/merchant policy
↓
Choose:
- retry
- notify
- payment link
- escalation
↓
Razorpay
↓
successful payment event
↓
₹999 recovered

Razorpay's documented subscription retry lifecycle is particularly useful because it provides a real payment state machine instead of requiring an entirely fake simulation.

---

# Razorpay Payment Links as recovery action

Potential flow:

Revenue at risk ₹4,999
↓
AI diagnosis
↓
Recovery strategy = Payment Link
↓
Razorpay API creates payment link
↓
Customer pays
↓
payment_link.paid
↓
Revenue recovered

This is an ideal example of:
**detect → decide → execute → verify.**

---

# Razorpay as a layer

Mental model:

Merchant
↓
YOUR AI REVENUE RECOVERY LAYER
↓
Orders / Payments / Subscriptions / Payment Links
↓
RAZORPAY
↓
Customers

Your project adds:
- revenue-risk detection
- context
- prediction
- decision-making
- optimization
- merchant policy
- orchestration
- attribution
- experimentation

Razorpay provides:
- payment/order state
- subscription state
- payment links
- webhooks
- actual test-mode transaction execution

---

# Razorpay relevance test

Ask:

> **"If I replaced Razorpay with Stripe, would 90% of my project still work?"**

If yes:
Probably too generic.

Desired answer:
> The core intelligence could be portable, but the event model, payment lifecycle, subscription recovery, Payment Links, webhook handling and actual execution are deeply integrated with Razorpay.

---

# Revenue Recovery Inbox

Potential UI:

AI Revenue Recovery

₹12.8L Revenue currently at risk
₹4.2L Recovered
34.7% Recovery rate

Active cases:

₹7,499 Payment failed
→ AI recommends Payment Link

₹4,999 Checkout abandoned
→ AI recommends 2% incentive

₹999 Subscription pending
→ AI recommends recovery sequence

Individual recovery case:

Recovery ID
Razorpay Order
Payment ID
Amount
Event
Failure reason
Customer history
AI decision
Merchant policy
Action
Webhook
Result

This should be a visualization of the financial decision system, not the main innovation.

---

# Testing architecture

Suggested:

Synthetic World
↓
Customers / Orders / Carts / Payments / Subscriptions
↓
Events / Cases
↓
Revenue Risk Detector
↓
AI Decision Engine
↓
Policy Engine
↓
Action Executor
↓
Razorpay Test APIs
↓
Simulator outcome + real test-mode outcome
↓
Measurement
↓
Experiment Engine

---

# Failure / chaos testing

Must deliberately test:

### Duplicate webhook
payment.success
payment.success
→ must not double-count.

### Race condition
Agent decides retry while payment succeeds.
→ re-check state and stop.

### Retry limit
Retry 1 → fail
Retry 2 → fail
Retry 3 → blocked.

### Policy violation
AI recommends 8%; merchant max = 5%.
→ policy rejects.

### Budget exhaustion
Budget = ₹100, AI wants ₹300.
→ block.

### Repeated abandonment
Customer repeatedly abandons.
→ eventually stop incentives.

### API failures
Recovery action/API fails.
→ retry safely or escalate.

This failure behavior is important because Track 3 explicitly asks for stopping rules, escalation and audit trail.

---

# Five levels of testing

### Level 1 — Unit
Policy engine and financial calculations.

### Level 2 — Workflow
End-to-end recovery workflow.

### Level 3 — Simulation
Thousands of cases vs baseline.

### Level 4 — Razorpay integration
Actual test-mode APIs/webhooks.

### Level 5 — Failure/chaos testing
Duplicate events, races, API errors, budget exhaustion, policy violations, etc.

---

# Brutal evaluations

## Weak version
"AI chatbot catches abandoned customers and gives coupons."

Approx. 6/10.

Problems:
- generic
- AI isn't necessary
- discount may destroy margin
- customer reasons may be unreliable
- coupon redemption doesn't prove causality
- intervention can itself annoy customers
- abandoned cart recovery is only one small part of revenue recovery

## Strong version
"AI revenue recovery system identifies revenue at risk, estimates whether intervention is economically worthwhile, chooses best merchant-approved recovery strategy, executes it, verifies outcome and measures incremental net revenue."

Approx. 8/10 conceptually.

Potentially much stronger if executed exceptionally.

---

# Most important differentiation

Do NOT optimize:

> recovery rate

Optimize:

> **incremental net merchant revenue/profit under a limited intervention/recovery budget.**

The agent should sometimes say:

> **NO ACTION**

because recovery itself has a cost.

---

# Recommended feature priority

## Tier S — MUST HAVE
1. Predictive revenue-risk detection.
2. Recovery decision engine.
3. Merchant policy constraints.
4. Real action execution.
5. Measured incremental revenue.
6. Failure handling.

## Tier A — strong differentiators
1. Recovery budget allocation.
2. Adaptive learning.
3. Multiple recovery workflows.
4. Revenue-at-risk dashboard.
5. Recovery attribution.

## Tier B — polish
1. Conversational recovery.
2. Recovery simulator.
3. Multi-agent strategy competition.

## Tier C — avoid unless everything else works
- Fancy multi-agent conversations.
- Generic RAG.
- Generic chatbot.
- Generic AI dashboards.
- Fake ML accuracy metrics.
- Competitor price scraping.

---

# Strong final thesis

## AI Revenue Recovery Optimizer

> An AI agent that continuously identifies revenue at risk, estimates the economic value of recovering each opportunity, allocates limited recovery resources, selects the least-cost effective intervention under merchant policy, executes it through Razorpay, verifies the result, attributes the recovery and learns from results.

Core loop:

DETECT
→ ESTIMATE REVENUE AT RISK
→ GENERATE CANDIDATE ACTIONS
→ OPTIMIZE EXPECTED NET RECOVERY
→ MERCHANT POLICY VALIDATION
→ EXECUTE
→ VERIFY
→ ATTRIBUTE
→ LEARN

Potential action space:

NO_ACTION
REMINDER
FREE_SHIPPING
DISCOUNT 1–5%
PRODUCT_ASSISTANCE
PAYMENT_RETRY
PAYMENT_LINK
SUBSCRIPTION_RECOVERY
HUMAN_ESCALATION

---

# Strongest demo concept

Merchant gives:

> ₹50,000 recovery/incentive budget.

System receives:

> 1,000 revenue-at-risk cases.

Agent allocates recovery resources.

Example final result:

REVENUE AT RISK: ₹12.8L
CASES: 1,000

NO ACTION: 312
REMINDERS: 241
PAYMENT RETRIES: 183
FREE SHIPPING: 97
DISCOUNTS: 84
HUMAN ESCALATIONS: 51
STOPPED: 32

GROSS RECOVERED: ₹4.21L
INCENTIVE COST: ₹31K
NET RECOVERED: ₹3.90L

BASELINE NET RECOVERY: ₹3.12L

INCREMENTAL IMPROVEMENT: +25%

Then drill into an individual case and show the entire audit trail.

Desired judge takeaway:

> **"The AI decided this revenue was worth saving, chose how much to spend to save it, respected the merchant's constraints, executed the recovery, and proved the incremental financial outcome."**

---

# Questions the user explicitly asked during the discussion

1. "what are these? explain in simple terms"
2. "so who is a merchant here"
3. "say if i had to choose between track 1 and track 3, how can i find problems/issues that is relevant to the track and is solvable"
4. "how"
5. "i want to go ahead with track 3, but before that i need everything about it. What type of dev must i be to pursue track 3? what must i enjoy doing?"
6. "i had a weird idea, if a user wants to abandon their cart with products in it... would such an idea come under this track?"
7. "be honest and critise my approach"
8. "is it though? given about 15 days? and the freedom to use any coding agent or AI. do you really think one solid feature is sufficient to land an internship at razorpay? i think youre wrong"
9. "what are the most common way of revenue loss? give me research backed answrs"
10. "what feature shld i think about to add to this workflow so that it makes my project stand out"
11. "but every other candidate will so probably get the same answer from their LLM. i want you to be brutally honest and risky"
12. "how apt are these features like predictive recovery, multi agents competing for the best recovery kinda stuff for the chosen track (3)?"
13. "before anything, how are the ways i can recreate such real world issues? how am i going to plan testing?"
14. "what am i trying to achieve"
15. "how can i make my project relevant to razorpay?"

---

# Final north star

The user is NOT trying to build:

> "An AI chatbot that gives coupons."

The user is trying to build:

> **A serious financial decision system that happens to use AI.**

It should demonstrate:
- AI/agent reasoning
- backend engineering
- payment infrastructure
- event-driven architecture
- state machines
- policy/guardrails
- idempotency
- failure handling
- experimentation
- causal/incremental measurement
- financial optimization
- Razorpay API/webhook integration

The constant question should be:

> **"Does this feature make the agent better at recovering incremental revenue, or is it just a cool AI feature?"**

If it's just a cool AI feature, cut it.
