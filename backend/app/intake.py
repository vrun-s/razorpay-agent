"""Creates a Recovery Case from a payment.failed webhook, then hands it to
the case lifecycle (app/lifecycle.py) for its first Reassessment (ticket 06:
a new case's first decision is not a separate code path from later ones).
"""

from typing import Any

from sqlmodel import Session

from app.gateway import Gateway
from app.lifecycle import log_entry, run_decision_cycle
from app.models import CaseHistoryEntryType, EventSource, ProcessedWebhookEvent, RecoveryCase, WorkflowType


def create_case_from_failed_payment(
    session: Session, gateway: Gateway, payment: dict[str, Any], event_id: str
) -> RecoveryCase:
    case = RecoveryCase(
        workflow_type=WorkflowType.FAILED_PAYMENT,
        source=EventSource.SIMULATED,
        external_reference_id=payment.get("id"),
    )
    session.add(case)
    session.add(ProcessedWebhookEvent(event_id=event_id, case_id=case.id))

    log_entry(
        session,
        case,
        CaseHistoryEntryType.CASE_CREATED,
        f"Recovery Case created from payment.failed for payment {payment.get('id')}",
        {"payment_id": payment.get("id"), "amount": payment.get("amount"), "currency": payment.get("currency")},
    )
    session.commit()
    session.refresh(case)

    return run_decision_cycle(session, gateway, case, payment=payment)
