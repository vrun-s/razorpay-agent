"""Runs a new Recovery Case through the ticket-01 tracer-bullet loop:
decide -> policy check -> (maybe) execute -- logging each step to Case History.
"""

from typing import Any

from sqlmodel import Session

from app.decision import decide
from app.gateway import Gateway
from app.models import (
    CaseHistoryEntry,
    CaseHistoryEntryType,
    EventSource,
    Intervention,
    ProcessedWebhookEvent,
    RecoveryCase,
    WorkflowType,
)
from app.policy import evaluate


def _log(session: Session, case: RecoveryCase, entry_type: CaseHistoryEntryType, summary: str, data: dict[str, Any] | None = None) -> None:
    session.add(CaseHistoryEntry(case_id=case.id, entry_type=entry_type, summary=summary, data=data or {}))


def create_case_from_failed_payment(
    session: Session, gateway: Gateway, payment: dict[str, Any], event_id: str
) -> RecoveryCase:
    case = RecoveryCase(workflow_type=WorkflowType.FAILED_PAYMENT, source=EventSource.SIMULATED)
    session.add(case)
    session.add(ProcessedWebhookEvent(event_id=event_id, case_id=case.id))

    _log(
        session,
        case,
        CaseHistoryEntryType.CASE_CREATED,
        f"Recovery Case created from payment.failed for payment {payment.get('id')}",
        {"payment_id": payment.get("id"), "amount": payment.get("amount"), "currency": payment.get("currency")},
    )

    intervention = decide(case)
    _log(
        session,
        case,
        CaseHistoryEntryType.DECISION,
        f"Decision Engine proposed {intervention.value}",
        {"intervention": intervention.value},
    )

    policy_result = evaluate(case, intervention)
    _log(
        session,
        case,
        CaseHistoryEntryType.POLICY_CHECK,
        f"Policy Engine {'approved' if policy_result.approved else 'rejected'} {intervention.value}",
        {"approved": policy_result.approved, "intervention": intervention.value, "reason": policy_result.reason},
    )

    if policy_result.approved and intervention == Intervention.PAYMENT_RETRY:
        result = gateway.create_payment_link(
            case_id=case.id,
            amount=payment.get("amount", 0),
            currency=payment.get("currency", "INR"),
            description=f"Complete your payment for order {payment.get('order_id', '')}",
            customer_contact={"email": payment.get("email", ""), "contact": payment.get("contact", "")},
        )
        _log(
            session,
            case,
            CaseHistoryEntryType.EXECUTION,
            f"Gateway created payment link {result.payment_link_id}",
            {"payment_link_id": result.payment_link_id, "short_url": result.short_url, "status": result.status},
        )

    session.commit()
    session.refresh(case)
    return case
