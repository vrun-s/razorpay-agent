"""Creates a Recovery Case from a payment.failed webhook, then hands it to
the case lifecycle (app/lifecycle.py) for its first Reassessment (ticket 06:
a new case's first decision is not a separate code path from later ones).
"""

from typing import Any

from sqlmodel import Session

from app.allocator import StreamingAllocator
from app.gateway import Gateway
from app.lifecycle import log_entry, run_decision_cycle
from app.models import CaseHistoryEntryType, EventSource, ProcessedWebhookEvent, RecoveryCase, WorkflowType


def create_case_from_failed_payment(
    session: Session,
    gateway: Gateway,
    payment: dict[str, Any],
    event_id: str,
    *,
    source: EventSource = EventSource.SIMULATED,
    allocator: StreamingAllocator | None = None,
) -> RecoveryCase:
    """`source` defaults to SIMULATED (every existing caller's behavior,
    unchanged); ticket 17's real-Razorpay integration slice is the first
    caller to pass `EventSource.REAL`, so its cases are excluded from the
    Decision Engine's posterior updates per ticket 07's exclusion rule
    (app/estimator.py's `Estimator.update` already checks `source` -- this
    is the first code path that ever sets it to anything else).

    `allocator` defaults to `run_decision_cycle`'s own default (the
    process-wide singleton) -- ticket 19's evaluation harness is the first
    caller to pass an explicit one, so a batch run's spend never leaks into
    live traffic's ledger or another run's.
    """
    case = RecoveryCase(
        workflow_type=WorkflowType.FAILED_PAYMENT,
        source=source,
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

    return run_decision_cycle(session, gateway, case, payment=payment, allocator=allocator)


def create_case_from_halted_subscription(
    session: Session,
    gateway: Gateway,
    subscription: dict[str, Any],
    event_id: str,
    *,
    source: EventSource = EventSource.SIMULATED,
    allocator: StreamingAllocator | None = None,
) -> RecoveryCase:
    """Ticket 12: proves [[0002-pluggable-workflow-abstraction]] for real -- the
    second workflow's detector, reusing the same engine (run_decision_cycle)
    matured on failed-payment rather than a parallel bespoke pipeline.

    `source`/`allocator` default the same way and for the same reasons as the
    sibling function above. Ticket 20 adds the first non-script caller to pass
    `source=EventSource.REAL`: `routers/webhooks.py` tags a case REAL when the
    app is wired to real Razorpay (`GATEWAY_BACKEND=razorpay`).
    """
    case = RecoveryCase(
        workflow_type=WorkflowType.HALTED_SUBSCRIPTION,
        source=source,
        external_reference_id=subscription.get("id"),
    )
    session.add(case)
    session.add(ProcessedWebhookEvent(event_id=event_id, case_id=case.id))

    log_entry(
        session,
        case,
        CaseHistoryEntryType.CASE_CREATED,
        f"Recovery Case created from subscription.halted for subscription {subscription.get('id')}",
        {"subscription_id": subscription.get("id"), "plan_id": subscription.get("plan_id")},
    )
    session.commit()
    session.refresh(case)

    return run_decision_cycle(session, gateway, case, payment=subscription, allocator=allocator)
