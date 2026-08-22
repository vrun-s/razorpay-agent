from fastapi import APIRouter, Depends
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.db import get_session
from app.models import RecoveryCase
from app.schemas import RecoveryCaseRead

router = APIRouter(tags=["cases"])


@router.get("/cases", response_model=list[RecoveryCaseRead])
def list_cases(session: Session = Depends(get_session)) -> list[RecoveryCase]:
    statement = select(RecoveryCase).options(selectinload(RecoveryCase.history)).order_by(RecoveryCase.created_at.desc())
    return list(session.exec(statement).all())
