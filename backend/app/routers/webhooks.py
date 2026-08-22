from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session

from app.db import get_session
from app.gateway import Gateway, get_gateway
from app.intake import create_case_from_failed_payment
from app.models import RecoveryCase
from app.schemas import RecoveryCaseRead

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _extract_failed_payment(payload: dict[str, Any]) -> dict[str, Any]:
    payment = payload.get("payload", {}).get("payment", {}).get("entity")
    if not payment or not payment.get("id"):
        raise HTTPException(status_code=400, detail="malformed payment.failed payload: missing payload.payment.entity")
    return payment


@router.post("/payment-failed", response_model=RecoveryCaseRead)
async def payment_failed(
    request: Request,
    session: Session = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
) -> RecoveryCase:
    """Accepts a synthetic `payment.failed`-shaped payload and creates a Recovery Case.

    Signature verification is out of scope here (ticket 04).
    """
    raw_body = await request.body()
    parsed = gateway.parse_webhook(headers=dict(request.headers), raw_body=raw_body)
    if parsed.event != "payment.failed":
        raise HTTPException(status_code=400, detail=f"expected event 'payment.failed', got {parsed.event!r}")

    payment = _extract_failed_payment(parsed.payload)
    # Off the event loop: same thread FastAPI would use for a sync `def` route,
    # keeping the blocking SQLModel session work consistent with ADR-0008.
    case = await run_in_threadpool(create_case_from_failed_payment, session, gateway, payment)
    return case
