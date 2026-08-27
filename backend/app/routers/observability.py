"""Ticket 18: the dashboard's read-only HTTP surface. Thin wrappers over
app/observability.py's projections plus the cached evaluation artifact --
nothing here writes state.
"""

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from app.db import get_session
from app.evaluation import DEFAULT_REPORT_PATH
from app.models import RecoveryCase
from app.observability import BudgetSnapshot, budget_timeline, case_flags, case_timeline
from app.schemas import BudgetSnapshotRead, CaseSummaryRead, CaseTimelineRead

router = APIRouter(tags=["observability"])


def _summary(case: RecoveryCase) -> CaseSummaryRead:
    return CaseSummaryRead(
        id=case.id,
        workflow_type=case.workflow_type,
        status=case.status,
        source=case.source,
        created_at=case.created_at,
        flags=case_flags(case),
    )


@router.get("/budget/timeline", response_model=list[BudgetSnapshotRead])
def get_budget_timeline(session: Session = Depends(get_session)) -> list[BudgetSnapshot]:
    """Every allocation decision so far, oldest-first -- the Reserved Budget
    as a moving quantity over the run (test2108.md §13 item 2)."""
    return budget_timeline(session)


@router.get("/observability/cases", response_model=list[CaseSummaryRead])
def list_case_summaries(session: Session = Depends(get_session)) -> list[CaseSummaryRead]:
    """Every case reduced to identity + state + demo-beat flags, for the
    timeline view's picker."""
    statement = (
        select(RecoveryCase)
        .options(selectinload(RecoveryCase.history))
        .order_by(RecoveryCase.created_at.desc())
    )
    return [_summary(case) for case in session.exec(statement).all()]


@router.get("/observability/cases/{case_id}/timeline", response_model=CaseTimelineRead)
def get_case_timeline(case_id: str, session: Session = Depends(get_session)) -> CaseTimelineRead:
    case = session.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail=f"no Recovery Case found for id {case_id!r}")
    return CaseTimelineRead(case=_summary(case), stages=case_timeline(case))


@router.get("/evaluation/report")
def get_evaluation_report() -> dict[str, Any]:
    """Serves the cached artifact written by `python -m app.evaluation`
    (test2108.md §13 items 5-6). 404 until it has been generated -- the
    dashboard renders that as an empty state naming the command to run."""
    if not DEFAULT_REPORT_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="evaluation report not generated yet — run: uv run python -m app.evaluation",
        )
    return json.loads(DEFAULT_REPORT_PATH.read_text())
