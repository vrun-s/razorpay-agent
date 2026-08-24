"""Case lifecycle: the reassessment loop (ticket 06, ADR-0004/0005).

A Recovery Case is a persistent sequence, not a one-shot decision: every
trigger -- case creation, an outcome-relevant webhook, or a Response Window
timeout -- runs the same decide -> policy check -> maybe execute cycle via
`run_decision_cycle`, and Case History accumulates across all of them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from app.allocator import AllocationCandidate, StreamingAllocator, get_allocator
from app.config import settings
from app.decision import VALID_INTERVENTIONS, DecisionInput, decide, resolve_cell_key, resolve_last_decided_cell_key
from app.estimator import CustomerHistory, get_estimator
from app.gateway import Gateway
from app.llm import LLMClient, get_llm_client
from app.models import (
    CaseHistoryEntry,
    CaseHistoryEntryType,
    CaseStatus,
    Intervention,
    ProcessedWebhookEvent,
    RecoveryCase,
    WorkflowType,
)
from app.policy import DEFAULT_POLICY_CONFIG, PolicyConfig, ProposedIntervention, validate

# Policy constraints that bound the *length* of a case's sequence (ADR-0004):
# once exceeded, no future proposal on this case can ever comply again (the
# count only grows), so the case is force-stopped rather than left open to
# be rejected identically on every future cycle.
_SEQUENCE_BOUND_CONSTRAINTS = {"max_payment_retries", "max_interventions_per_customer"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _customer_history_from_payment(payment: dict[str, Any]) -> CustomerHistory:
    """Ticket-07 stopgap: no real Customer History tracking exists yet (no
    cross-case customer identity -- the same disclosed gap ADR-0010 notes for
    `max_interventions_per_customer`), so this derives a single-order proxy
    from the payment the case is about. A real Customer History source is
    future work, not this ticket's.

    Disclosed gap (ticket 12): Razorpay's Subscription entity carries no
    `amount` field (that lives on the Plan, referenced only by `plan_id`), so
    a halted-subscription case's `avg_order_value` -- and, via the same
    `payment.get("amount", 0)` read in run_decision_cycle's `case_value` --
    its escalation_value_threshold check, always resolve to 0. Deriving a
    real value would need a Plan lookup this ticket doesn't add.
    """
    return CustomerHistory(order_count=1, avg_order_value=payment.get("amount", 0), payment_reliability_rate=0.5)


def _decline_text(payment: dict[str, Any]) -> str | None:
    """The unstructured decline text/bank code a payment.failed webhook carries
    (ticket 08, spec story 18) -- None if the payload has neither field, e.g.
    a scheduled-sweep reassessment that runs with no fresh payment at all."""
    error_code = payment.get("error_code")
    error_description = payment.get("error_description")
    if not error_code and not error_description:
        return None
    return f"{error_code or ''}: {error_description or ''}".strip(": ")


def _failure_reason_for_case(case: RecoveryCase, payment: dict[str, Any], llm_client: LLMClient) -> str | None:
    """LLM-diagnosed `failure_reason`, failed_payment workflow only (ADR-0009).

    A fresh decline text this cycle is re-diagnosed; otherwise (e.g. a
    scheduled-sweep reassessment with no payment payload) the case's own
    most recent DECISION entry already carries a diagnosis to reuse -- no
    need to re-derive it from nothing.
    """
    if case.workflow_type != WorkflowType.FAILED_PAYMENT:
        return None
    decline_text = _decline_text(payment)
    if decline_text:
        return llm_client.diagnose_failure_reason(decline_text=decline_text)
    last_cell = resolve_last_decided_cell_key(case)
    return last_cell.failure_reason if last_cell else None


def log_entry(
    session: Session, case: RecoveryCase, entry_type: CaseHistoryEntryType, summary: str, data: dict[str, Any] | None = None
) -> None:
    """Appends one Case History entry. Shared by intake.py (case creation) and this module."""
    session.add(CaseHistoryEntry(case_id=case.id, entry_type=entry_type, summary=summary, data=data or {}))


def run_decision_cycle(
    session: Session,
    gateway: Gateway,
    case: RecoveryCase,
    *,
    payment: dict[str, Any] | None = None,
    policy: PolicyConfig | None = None,
    llm_client: LLMClient | None = None,
    qualitative_signal: str | None = None,
    allocator: StreamingAllocator | None = None,
) -> RecoveryCase:
    """Runs one Reassessment: decide -> sequence-bound check -> policy check -> allocation check -> maybe execute.

    Called for a case's first decision (at creation) and every subsequent
    reassessment (webhook or scheduled-sweep triggered) alike -- there is no
    separate "first decision" code path.

    `qualitative_signal` (ticket 08's escalation-flag input) has no real
    source yet -- no support/chat channel exists in the pipeline -- so every
    caller today leaves it None; a future ticket wires a real one in.
    """
    payment = payment or {}
    policy = policy or DEFAULT_POLICY_CONFIG
    llm_client = llm_client or get_llm_client()
    allocator = allocator or get_allocator()

    failure_reason = _failure_reason_for_case(case, payment, llm_client)
    decision_input = DecisionInput(
        case=case,
        customer_history=_customer_history_from_payment(payment),
        failure_reason=failure_reason,
        qualitative_signal=qualitative_signal,
    )
    decision_output = decide(decision_input, llm_client=llm_client)
    intervention = decision_output.intervention
    cell_key = resolve_cell_key(decision_input, intervention)
    log_entry(
        session,
        case,
        CaseHistoryEntryType.DECISION,
        f"Decision Engine proposed {intervention.value}",
        {
            "intervention": intervention.value,
            "point_estimate": decision_output.point_estimate,
            "uncertainty": decision_output.uncertainty,
            "failure_reason": cell_key.failure_reason,
            "customer_segment_proxy": cell_key.customer_segment_proxy.value,
            "justification": decision_output.justification,
            "escalate": decision_output.escalate,
        },
    )

    proposal = ProposedIntervention(intervention=intervention)
    policy_result = validate(
        case, proposal, policy, budget_spent_so_far=allocator.ledger.spent, case_value=payment.get("amount", 0)
    )
    log_entry(
        session,
        case,
        CaseHistoryEntryType.POLICY_CHECK,
        f"Policy Engine {'approved' if policy_result.approved else 'rejected'} {intervention.value}",
        {
            "approved": policy_result.approved,
            "intervention": intervention.value,
            "violated_constraint": policy_result.violated_constraint,
            "proposed_value": policy_result.proposed_value,
            "reason": policy_result.reason,
            "escalate": policy_result.escalate,
        },
    )

    if decision_output.escalate or policy_result.escalate:
        reasons = []
        if decision_output.escalate:
            reasons.append("LLM flagged qualitative escalation signal")
        if policy_result.escalate:
            reasons.append(f"case value {payment.get('amount', 0)} met escalation_value_threshold {policy.escalation_value_threshold}")
        _escalate_case(session, case, reason="; ".join(reasons))
        session.commit()
        session.refresh(case)
        return case

    if not policy_result.approved and policy_result.violated_constraint in _SEQUENCE_BOUND_CONSTRAINTS:
        _stop_case(session, case, reason=policy_result.reason or f"{policy_result.violated_constraint} exceeded")
        session.commit()
        session.refresh(case)
        return case

    allocation_decision = None
    if policy_result.approved:
        allocation_decision = allocator.decide(
            AllocationCandidate(
                case_id=case.id,
                point_estimate=decision_output.point_estimate,
                uncertainty=decision_output.uncertainty,
                incentive_amount=proposal.incentive_amount,
            )
        )
        log_entry(
            session,
            case,
            CaseHistoryEntryType.ALLOCATION_CHECK,
            f"Streaming Allocator {'funded' if allocation_decision.funded else 'declined'} {intervention.value}",
            {
                "funded": allocation_decision.funded,
                "reason": allocation_decision.reason,
                "spent": allocation_decision.spent,
                "available": allocation_decision.available,
                "reserved": allocation_decision.reserved,
            },
        )

    funded = allocation_decision is not None and allocation_decision.funded
    if policy_result.approved and funded and intervention == Intervention.PAYMENT_RETRY:
        result = gateway.create_payment_link(
            case_id=case.id,
            amount=payment.get("amount", 0),
            currency=payment.get("currency", "INR"),
            description=f"Complete your payment for order {payment.get('order_id', '')}",
            customer_contact={"email": payment.get("email", ""), "contact": payment.get("contact", "")},
        )
        log_entry(
            session,
            case,
            CaseHistoryEntryType.EXECUTION,
            f"Gateway created payment link {result.payment_link_id}",
            {
                "payment_link_id": result.payment_link_id,
                "short_url": result.short_url,
                "status": result.status,
                "intervention": intervention.value,
            },
        )
    elif policy_result.approved and funded and intervention == Intervention.RESUME_CHARGE:
        result = gateway.resume_charge(case_id=case.id, subscription_id=case.external_reference_id or "")
        log_entry(
            session,
            case,
            CaseHistoryEntryType.EXECUTION,
            f"Gateway resumed charge for subscription {result.subscription_id}",
            {
                "subscription_id": result.subscription_id,
                "status": result.status,
                "intervention": intervention.value,
            },
        )

    if case.status == CaseStatus.OPEN:
        case.response_window_expires_at = _now() + timedelta(seconds=settings.response_window_seconds)
        session.add(case)

    session.commit()
    session.refresh(case)
    return case


def _stop_case(session: Session, case: RecoveryCase, *, reason: str) -> None:
    case.status = CaseStatus.STOPPED
    case.response_window_expires_at = None
    session.add(case)
    log_entry(session, case, CaseHistoryEntryType.CASE_STOPPED, f"Case stopped: {reason}", {"reason": reason})


def _escalate_case(session: Session, case: RecoveryCase, *, reason: str) -> None:
    case.status = CaseStatus.ESCALATED
    case.response_window_expires_at = None
    session.add(case)
    log_entry(session, case, CaseHistoryEntryType.CASE_ESCALATED, f"Case escalated: {reason}", {"reason": reason})


def _case_created_payment_data(case: RecoveryCase) -> dict[str, Any]:
    """The amount/currency intake.py logged at case creation (ticket 09's
    override has no fresh payment payload of its own to work from)."""
    created = next((e for e in case.history if e.entry_type == CaseHistoryEntryType.CASE_CREATED), None)
    return created.data if created else {}


def override_case(session: Session, gateway: Gateway, case: RecoveryCase, *, intervention: Intervention) -> RecoveryCase:
    """Ticket 09: a human overrides an Escalated case with their own chosen
    Intervention. Skips the Decision Engine's probabilistic choice -- the
    human already decided -- but reuses the same DECISION/EXECUTION entry
    shapes and Gateway seam a Reassessment would, so Case History carries no
    side channel.
    """
    if intervention not in VALID_INTERVENTIONS[case.workflow_type]:
        raise ValueError(f"{intervention.value} is not a valid intervention for {case.workflow_type.value}")

    log_entry(
        session,
        case,
        CaseHistoryEntryType.DECISION,
        f"Human override selected {intervention.value}",
        {"intervention": intervention.value, "source": "human"},
    )

    if intervention == Intervention.PAYMENT_RETRY:
        payment_data = _case_created_payment_data(case)
        result = gateway.create_payment_link(
            case_id=case.id,
            amount=payment_data.get("amount", 0),
            currency=payment_data.get("currency", "INR"),
            description=f"Complete your payment for case {case.id}",
            customer_contact={},  # no fresh payment payload at override time -- disclosed gap
        )
        log_entry(
            session,
            case,
            CaseHistoryEntryType.EXECUTION,
            f"Gateway created payment link {result.payment_link_id}",
            {
                "payment_link_id": result.payment_link_id,
                "short_url": result.short_url,
                "status": result.status,
                "intervention": intervention.value,
                "source": "human",
            },
        )
    elif intervention == Intervention.RESUME_CHARGE:
        result = gateway.resume_charge(case_id=case.id, subscription_id=case.external_reference_id or "")
        log_entry(
            session,
            case,
            CaseHistoryEntryType.EXECUTION,
            f"Gateway resumed charge for subscription {result.subscription_id}",
            {
                "subscription_id": result.subscription_id,
                "status": result.status,
                "intervention": intervention.value,
                "source": "human",
            },
        )

    case.status = CaseStatus.OPEN
    case.response_window_expires_at = _now() + timedelta(seconds=settings.response_window_seconds)
    session.add(case)
    session.commit()
    session.refresh(case)
    return case


def resolve_case_manually(session: Session, case: RecoveryCase, *, outcome: CaseStatus, reason: str) -> RecoveryCase:
    """Ticket 09: a human closes an Escalated case directly -- no outcome
    webhook backs this, so it reuses the same CASE_RECOVERED/CASE_STOPPED
    entry shape a real outcome would, tagged as human-resolved, instead of a
    side channel. `outcome` is RECOVERED or STOPPED (caller-validated).
    """
    case.status = outcome
    case.response_window_expires_at = None
    session.add(case)

    if outcome == CaseStatus.RECOVERED:
        log_entry(
            session, case, CaseHistoryEntryType.CASE_RECOVERED, f"Case recovered: {reason}",
            {"reason": reason, "resolved_by": "human"},
        )
        cell_key = resolve_last_decided_cell_key(case)
        if cell_key is not None:
            get_estimator().update(cell_key, source=case.source, success=True)
    else:
        log_entry(
            session, case, CaseHistoryEntryType.CASE_STOPPED, f"Case stopped: {reason}",
            {"reason": reason, "resolved_by": "human"},
        )

    session.commit()
    session.refresh(case)
    return case


def record_processed_event(session: Session, event_id: str, case: RecoveryCase) -> None:
    """Dedup bookkeeping only, for a webhook that turned out to be a no-op (e.g. an already-resolved case)."""
    session.add(ProcessedWebhookEvent(event_id=event_id, case_id=case.id))
    session.commit()


def mark_recovered(session: Session, case: RecoveryCase, event_id: str, *, reason: str) -> RecoveryCase:
    """Closes a case as recovered -- a real outcome arrived, so no further Reassessment is needed.

    Feeds the outcome back into the estimator's cell for whatever intervention
    was last proposed (ADR-0006's online update rule) -- excluded entirely
    for a `real`-tagged case, per the estimator's own source check.

    Records the triggering webhook's dedup entry in the same commit as the
    state transition, exactly like intake.py's case creation -- one atomic
    write, not two.
    """
    session.add(ProcessedWebhookEvent(event_id=event_id, case_id=case.id))
    case.status = CaseStatus.RECOVERED
    case.response_window_expires_at = None
    session.add(case)
    log_entry(session, case, CaseHistoryEntryType.CASE_RECOVERED, f"Case recovered: {reason}", {"reason": reason})

    cell_key = resolve_last_decided_cell_key(case)
    if cell_key is not None:
        get_estimator().update(cell_key, source=case.source, success=True)

    session.commit()
    session.refresh(case)
    return case


def due_cases(session: Session, *, now: datetime | None = None) -> list[RecoveryCase]:
    """OPEN cases whose Response Window has elapsed with no outcome (ADR-0005)."""
    now = now or _now()
    statement = select(RecoveryCase).where(
        RecoveryCase.status == CaseStatus.OPEN,
        RecoveryCase.response_window_expires_at.is_not(None),
        RecoveryCase.response_window_expires_at <= now,
    )
    return list(session.exec(statement).all())


def run_sweep(
    session: Session, gateway: Gateway, *, now: datetime | None = None, policy: PolicyConfig | None = None
) -> list[RecoveryCase]:
    """The scheduled-sweep trigger (ADR-0005): reassess every case whose silence is now itself a signal."""
    policy = policy or DEFAULT_POLICY_CONFIG
    cases = due_cases(session, now=now)
    for case in cases:
        log_entry(
            session,
            case,
            CaseHistoryEntryType.REASSESSMENT_TRIGGERED,
            "Response Window elapsed with no outcome",
            {"trigger": "scheduled_sweep"},
        )
        session.commit()
        run_decision_cycle(session, gateway, case, policy=policy)
    return cases
