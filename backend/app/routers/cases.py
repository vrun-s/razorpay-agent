from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.config import settings
from app.db import get_session
from app.decision import VALID_INTERVENTIONS
from app.gateway import Gateway, get_gateway
from app.lifecycle import override_case, resolve_case_manually
from app.models import CaseStatus, RecoveryCase
from app.schemas import OverrideRequest, RecoveryCaseRead, ResolveRequest

router = APIRouter(tags=["cases"])


def require_writable() -> None:
    """ADR-0015: the public hosted instance runs with DEMO_READONLY=true and
    rejects the human-action endpoints. `/config` tells the SPA to hide the
    controls; this is the enforcement behind them."""
    if settings.demo_readonly:
        raise HTTPException(status_code=403, detail="this instance is a read-only demo")


@router.get("/cases", response_model=list[RecoveryCaseRead])
def list_cases(session: Session = Depends(get_session)) -> list[RecoveryCase]:
    statement = select(RecoveryCase).options(selectinload(RecoveryCase.history)).order_by(RecoveryCase.created_at.desc())
    return list(session.exec(statement).all())


def _get_escalated_case(session: Session, case_id: str) -> RecoveryCase:
    case = session.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no Recovery Case found for id {case_id!r}")
    if case.status != CaseStatus.ESCALATED:
        raise HTTPException(status_code=409, detail=f"case {case_id} is not Escalated (status={case.status.value})")
    return case


@router.post("/cases/{case_id}/override", response_model=RecoveryCaseRead, dependencies=[Depends(require_writable)])
def override(
    case_id: str,
    body: OverrideRequest,
    session: Session = Depends(get_session),
    gateway: Gateway = Depends(get_gateway),
) -> RecoveryCase:
    """Ticket 09: a human overrides an Escalated case with their own chosen Intervention."""
    case = _get_escalated_case(session, case_id)
    # Same check as override_case's own guard -- deliberate: this one turns an
    # invalid choice into a clean 400 for the API caller, before it ever
    # reaches the domain layer's ValueError.
    if body.intervention not in VALID_INTERVENTIONS[case.workflow_type]:
        raise HTTPException(
            status_code=400, detail=f"{body.intervention.value} is not valid for {case.workflow_type.value}"
        )
    return override_case(session, gateway, case, intervention=body.intervention)


@router.post("/cases/{case_id}/resolve", response_model=RecoveryCaseRead, dependencies=[Depends(require_writable)])
def resolve(case_id: str, body: ResolveRequest, session: Session = Depends(get_session)) -> RecoveryCase:
    """Ticket 09: a human manually resolves/closes an Escalated case."""
    case = _get_escalated_case(session, case_id)
    outcome = CaseStatus.RECOVERED if body.outcome == "recovered" else CaseStatus.STOPPED
    return resolve_case_manually(session, case, outcome=outcome, reason=body.reason)
