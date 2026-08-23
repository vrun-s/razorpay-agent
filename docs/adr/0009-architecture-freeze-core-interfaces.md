# Freeze five core interfaces before ticket 04

Ticket 01 (tracer bullet) and ticket 02 (simulator generator) are done, and every ticket from 04 onward builds directly on top of the shapes those two established — Webhook Ingestion hardening (04), Policy Engine constraints (05), the Decision Engine estimator (07), and the real-Razorpay Executor (13) all assume specific field names and function signatures rather than re-deriving them. Freezing those shapes now, in one place, means a later ticket that wants to change one has to make that a deliberate, documented decision instead of a silent one made mid-implementation. This ADR is that checkpoint, per ticket 03.

**Decision**: The following five shapes are locked as of this ADR. None of them change from ticket 04 onward without a new ADR recorded here.

- **Recovery Case schema** (`app/models.py`, as built in ticket 01) — `RecoveryCase`: `id` (UUID string, the `recovery_id`), `workflow_type` (`WorkflowType`: `failed_payment` | `halted_subscription`), `status` (`CaseStatus`: `open` | `recovered` | `stopped` | `escalated`), `source` (`EventSource`: `real` | `simulated` — the per-case tag ADR-0006's estimator exclusion rule depends on), `created_at`, and an ordered `history: list[CaseHistoryEntry]`. Each `CaseHistoryEntry` carries `entry_type` (`case_created` | `decision` | `policy_check` | `execution` — this set grows additively as new lifecycle events need their own entry type, never replaced), a `summary` string for display, and a free-form `data: dict` for structured detail. `EventSource` lives per-case today; per-history-entry source tagging (spec user story 6) is additive when needed, not a redesign.

- **Shared `Intervention` type** (`app/models.py`) — one `StrEnum` (`payment_retry`, `resume_charge`, `no_action`) used by every workflow, per [[0002-pluggable-workflow-abstraction]]. Valid subsets per workflow: `failed_payment` → `{payment_retry, no_action}`; `halted_subscription` → `{resume_charge, no_action}`. `no_action` is valid in both — it is never the workflow-specific action, always the deliberate "do nothing" choice (CONTEXT.md: Intervention). No workflow subset check exists in code yet (ticket 01 only ever proposes `payment_retry`); enforcing the subset is later work, against this fixed enum.

- **Gateway/Executor interface** (`app/gateway.py`) — the `Gateway` `Protocol`, unchanged from ticket 01:
  ```python
  class Gateway(Protocol):
      def create_payment_link(self, *, case_id: str, amount: int, currency: str,
                               description: str, customer_contact: dict[str, str]) -> PaymentLinkResult: ...
      def resume_charge(self, *, case_id: str, subscription_id: str) -> ResumeChargeResult: ...
      def parse_webhook(self, *, headers: dict[str, str], raw_body: bytes) -> ParsedWebhookEvent: ...
  ```
  `PaymentLinkResult`, `ResumeChargeResult`, and `ParsedWebhookEvent` are frozen dataclasses; their fields (`payment_link_id`/`short_url`/`status`, `subscription_id`/`status`, `event`/`payload`) are part of the frozen shape. `FakeGateway` (simulator-driven) and the future real-Razorpay gateway (ticket 13) both satisfy this same `Protocol` — the recovery engine's core code (`app/intake.py` and whatever replaces it) only ever depends on `Gateway`, never on which implementation it holds.

- **Policy Engine contract** — **superseded by [[0010-policy-engine-validate-contract]]**, written when ticket 05 implemented this against the sketch below and found it didn't fit (no field here carries a discount/incentive value to check, and `fallback_intervention` contradicts ticket 05's "rejected outright, never downgraded" rule). Left here for history only; treat ADR-0010 as current. Original sketch (intended, ahead of ticket 05 — `app/policy.py` was ticket 01's pass-through stub): `validate(case: RecoveryCase, intervention: Intervention, policy: PolicyConfig) -> PolicyResult`, where `PolicyConfig` is the merchant-defined constraint set (`max_discount_pct`, `max_incentive_amount`, `max_payment_retries`, `max_halted_recovery_attempts`, `max_interventions_per_customer`, escalation thresholds — spec user stories 23–25), and `PolicyResult` added `violated_constraint` and `fallback_intervention` fields to the stub's three.

- **Decision Engine interface** (intended, ahead of ticket 07 — `app/decision.py` today is ticket 01's fixed-rule stub) — per [[0006-decision-engine-estimator]], the estimator consumes Case History (already on `RecoveryCase.history`) and Customer History, plus an LLM-diagnosed `failure_reason` for failed-payment cases, and returns a point estimate *and* an explicit uncertainty measure — never the point estimate alone, since the streaming allocator ([[0003-streaming-allocation]]) needs both:
  ```python
  @dataclass(frozen=True)
  class DecisionInput:
      case: RecoveryCase           # Case History via case.history
      customer_history: CustomerHistory   # order_count, avg_order_value, payment_reliability_rate
      failure_reason: str | None   # LLM-diagnosed; failed_payment workflow only

  @dataclass(frozen=True)
  class DecisionOutput:
      intervention: Intervention
      point_estimate: float        # Beta-Bernoulli posterior mean
      uncertainty: float           # credible interval width
      justification: str           # LLM-generated, for the audit trail
      escalate: bool                # LLM-flagged qualitative escalation signal

  def decide(input: DecisionInput) -> DecisionOutput
  ```
  `CustomerHistory` and the `customer_segment_proxy` threshold logic are new types ticket 07 introduces; this ADR fixes only the input/output envelope around them, not their internals.

**Consequences**: Tickets 04–18 build against these five shapes as given, not as something each ticket is free to redesign. Where a stub's current shape (`policy.evaluate`, `decision.decide`) differs from the frozen intended contract, the implementing ticket (05, 07) is expected to converge on the shape documented here rather than inventing a new one — and if a later ticket finds this ADR's shape genuinely doesn't work, that's a new ADR superseding the relevant part of this one, not a silent signature change.
