from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.models import CaseHistoryEntryType, CaseStatus, EventSource, Intervention, WorkflowType


class CaseHistoryEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    entry_type: CaseHistoryEntryType
    summary: str
    data: dict[str, Any]


class RecoveryCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow_type: WorkflowType
    status: CaseStatus
    source: EventSource
    created_at: datetime
    history: list[CaseHistoryEntryRead]


class OverrideRequest(BaseModel):
    """Ticket 09: a human's chosen Intervention for an Escalated case."""

    intervention: Intervention


class ResolveRequest(BaseModel):
    """Ticket 09: a human manually closing an Escalated case."""

    outcome: Literal["recovered", "stopped"]
    reason: str
