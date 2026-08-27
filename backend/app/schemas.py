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


class BudgetSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    timestamp: datetime
    case_id: str
    funded: bool
    reason: str
    spent: int
    available: int
    reserved: int


class CaseFlagsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    no_action_recovered: bool
    policy_rejected: bool
    human_overridden: bool
    escalated: bool


class CaseSummaryRead(BaseModel):
    """A case reduced to what the dashboard's picker needs: identity, state,
    and its demo-beat flags (ticket 18). Built explicitly in the router (it
    joins `RecoveryCase` fields with a computed `flags`), so unlike
    `RecoveryCaseRead` it needs no `from_attributes`."""

    id: str
    workflow_type: WorkflowType
    status: CaseStatus
    source: EventSource
    created_at: datetime
    flags: CaseFlagsRead


class TimelineStageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    stage: str
    label: str
    timestamp: datetime
    entry_type: str
    detail: dict[str, Any]


class CaseTimelineRead(BaseModel):
    case: CaseSummaryRead
    stages: list[TimelineStageRead]


class OverrideRequest(BaseModel):
    """Ticket 09: a human's chosen Intervention for an Escalated case."""

    intervention: Intervention


class ResolveRequest(BaseModel):
    """Ticket 09: a human manually closing an Escalated case."""

    outcome: Literal["recovered", "stopped"]
    reason: str
