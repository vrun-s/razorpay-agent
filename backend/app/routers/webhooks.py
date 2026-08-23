from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from app.config import settings
from app.db import get_session
from app.gateway import Gateway, get_gateway
from app.intake import create_case_from_failed_payment
from app.models import ProcessedWebhookEvent, RecoveryCase
from app.schemas import RecoveryCaseRead
from app.webhook_security import InvalidWebhookSignatureError, verify

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _extract_failed_payment(payload: dict[str, Any]) -> dict[str, Any]:
    payment = payload.get("payload", {}).get("payment", {}).get("entity")
    if not payment or not payment.get("id"):
        raise HTTPException(status_code=400, detail="malformed payment.failed payload: missing payload.payment.entity")
    return payment


def _verify_and_get_event_id(request: Request, raw_body: bytes) -> str:
    """Verify the HMAC-SHA256 signature and return the dedup event id, or raise HTTPException."""
    event_id = request.headers.get("x-razorpay-event-id")
    if not event_id:
        raise HTTPException(status_code=400, detail="missing x-razorpay-event-id header")

    signature = request.headers.get("x-razorpay-signature")
    if not signature:
        raise HTTPException(status_code=400, detail="missing x-razorpay-signature header")

    if not settings.razorpay_webhook_secret:
        raise HTTPException(status_code=500, detail="RAZORPAY_WEBHOOK_SECRET is not configured")

    try:
        verify(raw_body=raw_body, signature=signature, secret=settings.razorpay_webhook_secret)
    except InvalidWebhookSignatureError:
        raise HTTPException(status_code=400, detail="invalid webhook signature") from None

    return event_id


def _case_for_processed_event(session: Session, event_id: str) -> RecoveryCase | None:
    processed = session.get(ProcessedWebhookEvent, event_id)
    if processed is None:
        return None
    return session.get(RecoveryCase, processed.case_id)


@router.post("/payment-failed", response_model=RecoveryCaseRead)
async def payment_failed(
    request: Request,
    session: Session = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
) -> RecoveryCase:
    """Verifies a `payment.failed` webhook and creates a Recovery Case (ticket 04).

    A repeated `x-razorpay-event-id` is a no-op that returns the case already
    created for it, never a second case.
    """
    raw_body = await request.body()
    event_id = _verify_and_get_event_id(request, raw_body)

    existing_case = await run_in_threadpool(_case_for_processed_event, session, event_id)
    if existing_case is not None:
        return existing_case

    parsed = gateway.parse_webhook(headers=dict(request.headers), raw_body=raw_body)
    if parsed.event != "payment.failed":
        raise HTTPException(status_code=400, detail=f"expected event 'payment.failed', got {parsed.event!r}")

    payment = _extract_failed_payment(parsed.payload)
    # Off the event loop: same thread FastAPI would use for a sync `def` route,
    # keeping the blocking SQLModel session work consistent with ADR-0008.
    case = await run_in_threadpool(create_case_from_failed_payment, session, gateway, payment, event_id)
    return case
